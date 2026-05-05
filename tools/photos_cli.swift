// photos_cli.swift — Mac Photos.app 통합 CLI (PhotoKit Framework).
//
// 명령:
//   delete <UUID>...                  사진 삭제 (휴지통으로 이동, 30일 안전망)
//   album-add <album_name> <UUID>...  사진을 사용자 앨범에 추가 (없으면 생성)
//
// stdin/argv UUID 입력. JSON 출력.
//
// 빌드: swiftc -O tools/photos_cli.swift -o tools/photos_cli -framework Photos
//
// 사용:
//   echo "UUID" | tools/photos_cli delete
//   tools/photos_cli album-add "✦ BEST" UUID1 UUID2 ...
//
// AppleScript 우회 — macOS 업데이트 호환성 보장 (Apple 공식 API).

import Foundation
import Photos

func requestAccess() -> Bool {
    let status = PHPhotoLibrary.authorizationStatus(for: .readWrite)
    if status == .authorized || status == .limited { return true }
    if status == .denied || status == .restricted { return false }
    let semaphore = DispatchSemaphore(value: 0)
    var ok = false
    PHPhotoLibrary.requestAuthorization(for: .readWrite) { s in
        ok = (s == .authorized || s == .limited)
        semaphore.signal()
    }
    semaphore.wait()
    return ok
}

func fetchAssets(_ uuids: [String]) -> [PHAsset] {
    let r = PHAsset.fetchAssets(withLocalIdentifiers: uuids, options: nil)
    var assets: [PHAsset] = []
    r.enumerateObjects { a, _, _ in assets.append(a) }
    return assets
}

func findOrCreateAlbum(_ name: String) -> PHAssetCollection? {
    // 기존 앨범 검색
    let opts = PHFetchOptions()
    opts.predicate = NSPredicate(format: "title == %@", name)
    let r = PHAssetCollection.fetchAssetCollections(
        with: .album, subtype: .albumRegular, options: opts)
    if r.count > 0 { return r.firstObject }

    // 신규 생성
    let semaphore = DispatchSemaphore(value: 0)
    var placeholder: PHObjectPlaceholder? = nil
    var success = false
    PHPhotoLibrary.shared().performChanges({
        let req = PHAssetCollectionChangeRequest.creationRequestForAssetCollection(
            withTitle: name)
        placeholder = req.placeholderForCreatedAssetCollection
    }, completionHandler: { ok, _ in
        success = ok
        semaphore.signal()
    })
    semaphore.wait()
    if !success || placeholder == nil { return nil }

    let r2 = PHAssetCollection.fetchAssetCollections(
        withLocalIdentifiers: [placeholder!.localIdentifier], options: nil)
    return r2.firstObject
}

func deleteAssets(_ assets: [PHAsset]) -> (Int, String?) {
    let semaphore = DispatchSemaphore(value: 0)
    var success = false
    var err: String? = nil
    PHPhotoLibrary.shared().performChanges({
        PHAssetChangeRequest.deleteAssets(assets as NSFastEnumeration)
    }, completionHandler: { ok, e in
        success = ok
        err = e?.localizedDescription
        semaphore.signal()
    })
    semaphore.wait()
    return (success ? assets.count : 0, err)
}

func addAssetsToAlbum(_ album: PHAssetCollection, _ assets: [PHAsset]) -> (Int, String?) {
    let semaphore = DispatchSemaphore(value: 0)
    var success = false
    var err: String? = nil
    PHPhotoLibrary.shared().performChanges({
        guard let req = PHAssetCollectionChangeRequest(for: album) else { return }
        // 중복 추가 방지 — 이미 있는 자산 필터
        let existing = PHAsset.fetchAssets(in: album, options: nil)
        var existingIds = Set<String>()
        existing.enumerateObjects { a, _, _ in existingIds.insert(a.localIdentifier) }
        let newAssets = assets.filter { !existingIds.contains($0.localIdentifier) }
        if !newAssets.isEmpty {
            req.addAssets(newAssets as NSFastEnumeration)
        }
    }, completionHandler: { ok, e in
        success = ok
        err = e?.localizedDescription
        semaphore.signal()
    })
    semaphore.wait()
    return (success ? assets.count : 0, err)
}

struct Result: Codable {
    let command: String
    let processed: Int
    let not_found: Int
    let failed: Int
    let error: String?
}

func emitJson(_ r: Result) {
    let enc = JSONEncoder()
    let data = try! enc.encode(r)
    print(String(data: data, encoding: .utf8)!)
}

func main() -> Int32 {
    let args = CommandLine.arguments
    guard args.count >= 2 else {
        FileHandle.standardError.write("Usage: photos_cli <delete|album-add> ...\n".data(using: .utf8)!)
        return 1
    }
    let cmd = args[1]

    if !requestAccess() {
        FileHandle.standardError.write("권한 거부 — 시스템 설정 → 사진 → photos_cli 허용\n".data(using: .utf8)!)
        return 2
    }

    var uuids: [String] = []
    var albumName: String? = nil

    switch cmd {
    case "delete":
        if args.count > 2 {
            uuids = Array(args[2...])
        } else {
            while let line = readLine() {
                let t = line.trimmingCharacters(in: .whitespaces)
                if !t.isEmpty { uuids.append(t) }
            }
        }
        let assets = fetchAssets(uuids)
        let foundIds = Set(assets.map { $0.localIdentifier })
        let notFound = uuids.filter { !foundIds.contains($0) }.count
        let (deleted, err) = assets.isEmpty ? (0, nil) : deleteAssets(assets)
        emitJson(Result(command: "delete", processed: deleted,
                        not_found: notFound, failed: assets.count - deleted, error: err))
        return assets.count - deleted > 0 ? 1 : 0

    case "album-add":
        guard args.count >= 4 else {
            FileHandle.standardError.write(
                "Usage: photos_cli album-add <album_name> <UUID>...\n".data(using: .utf8)!)
            return 1
        }
        albumName = args[2]
        uuids = Array(args[3...])
        guard let album = findOrCreateAlbum(albumName!) else {
            emitJson(Result(command: "album-add", processed: 0, not_found: 0,
                            failed: uuids.count, error: "album_create_failed"))
            return 1
        }
        let assets = fetchAssets(uuids)
        let foundIds = Set(assets.map { $0.localIdentifier })
        let notFound = uuids.filter { !foundIds.contains($0) }.count
        let (added, err) = assets.isEmpty ? (0, nil) : addAssetsToAlbum(album, assets)
        emitJson(Result(command: "album-add", processed: added,
                        not_found: notFound, failed: assets.count - added, error: err))
        return 0

    default:
        FileHandle.standardError.write("Unknown command: \(cmd)\n".data(using: .utf8)!)
        return 1
    }
}

exit(main())
