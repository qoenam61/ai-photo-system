// photos_cli.swift — Mac Photos.app 통합 CLI (PhotoKit Framework).
//
// 명령:
//   delete <UUID>...                  사진 삭제 (휴지통으로 이동, 30일 안전망)
//   album-add <album_name> <UUID>...  사진을 사용자 앨범에 추가 (없으면 생성)
//   delete-by-meta --input FILE --output FILE
//                                     filename+ISO_date 직접 검색 → 삭제
//                                     iCloud-only 자산도 매칭 (osxphotos 한계 우회)
//                                     2026-05-08 P0-C 근본해결.
//
// stdin/argv UUID 입력. JSON 출력.
//
// 빌드: swiftc -O tools/photos_cli.swift -o tools/photos_cli -framework Photos
//
// 사용:
//   echo "UUID" | tools/photos_cli delete
//   tools/photos_cli album-add "✦ BEST" UUID1 UUID2 ...
//   echo -e "IMG_0788.HEIC\t2024-08-15T14:23:11+09:00" | tools/photos_cli delete-by-meta
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


// 2026-05-08 P0-C: filename + ISO date → PHAsset 직접 검색.
// osxphotos PhotosDB는 iCloud-only 자산을 인덱싱 못 하지만, PHAsset.fetchAssets는 OK.
//
// 입력 (--input FILE): line별 "filename\tISO8601_date"
// 출력 (--output FILE 또는 stdout): JSON
//   {"command":"delete-by-meta","processed":N,"not_found":M,"failed":K,"error":...}
//
// 매칭 정책:
//   1. creationDate ±2초 범위로 fetch (Predicate)
//   2. value(forKey: "filename") == filename 검증
//   3. 매칭된 PHAsset 일괄 삭제

func parseISODate(_ s: String) -> Date? {
    // ISO8601 + fallback ("YYYY-MM-DD HH:MM:SS")
    if let d = ISO8601DateFormatter().date(from: s) { return d }
    let f = DateFormatter()
    f.dateFormat = "yyyy-MM-dd HH:mm:ss"
    f.timeZone = TimeZone.current
    if let d = f.date(from: s) { return d }
    f.dateFormat = "yyyy-MM-dd'T'HH:mm:ss"
    return f.date(from: s)
}

func findAssetsByMeta(_ entries: [(filename: String, date: Date)],
                     toleranceSec: TimeInterval = 2.0) -> [PHAsset] {
    // 매칭 정책 (2026-05-08 P0-C):
    //   1. creationDate ±2초 내 PHAsset 후보 fetch
    //   2. filename 정확 매칭 우선 (Mac Photos에 직접 import된 자산)
    //   3. 단일 후보면 filename 무관 매칭 — Immich가 UUID로 rename한 자산
    //      (iPhone 직접 업로드: PHAsset filename=IMG_XXXX vs Immich filename=UUID)
    //   4. 다중 후보면 filename 정확 매칭 안 되는 경우 SKIP (안전)
    var matched: [PHAsset] = []
    var matchedIds = Set<String>()
    for entry in entries {
        let lower = entry.date.addingTimeInterval(-toleranceSec)
        let upper = entry.date.addingTimeInterval(toleranceSec)
        let opts = PHFetchOptions()
        opts.predicate = NSPredicate(
            format: "(creationDate >= %@) AND (creationDate <= %@)",
            lower as NSDate, upper as NSDate)
        let r = PHAsset.fetchAssets(with: opts)
        var candidates: [PHAsset] = []
        r.enumerateObjects { a, _, _ in candidates.append(a) }

        var winner: PHAsset? = nil
        // 정확 filename 매칭 시도 (PHAsset.value(forKey:"filename") 비공개 API지만 안정)
        for a in candidates {
            if let aName = a.value(forKey: "filename") as? String,
               aName == entry.filename {
                winner = a
                break
            }
        }
        // 단일 후보 + filename 매칭 X → 같은 자산으로 추정 (UUID rename 흡수)
        if winner == nil && candidates.count == 1 {
            winner = candidates.first
        }

        if let w = winner, !matchedIds.contains(w.localIdentifier) {
            matched.append(w)
            matchedIds.insert(w.localIdentifier)
        }
    }
    return matched
}

func readMetaFromFile(_ path: String) -> [(filename: String, date: Date)] {
    guard let content = try? String(contentsOfFile: path, encoding: .utf8) else { return [] }
    var out: [(String, Date)] = []
    for line in content.split(separator: "\n") {
        let trimmed = String(line).trimmingCharacters(in: .whitespaces)
        if trimmed.isEmpty { continue }
        let parts = trimmed.components(separatedBy: "\t")
        if parts.count < 2 { continue }
        guard let d = parseISODate(parts[1]) else { continue }
        out.append((parts[0], d))
    }
    return out
}

var outputFilePath: String? = nil

func emitJson(_ r: Result) {
    let enc = JSONEncoder()
    let data = try! enc.encode(r)
    let s = String(data: data, encoding: .utf8)!
    if let path = outputFilePath {
        try? s.write(toFile: path, atomically: true, encoding: .utf8)
    } else {
        print(s)
    }
}

func readUuidsFromFile(_ path: String) -> [String] {
    guard let content = try? String(contentsOfFile: path, encoding: .utf8) else { return [] }
    return content.split(separator: "\n")
        .map { String($0).trimmingCharacters(in: .whitespaces) }
        .filter { !$0.isEmpty }
}

func parseFlags(_ args: [String]) -> (cmd: String, params: [String], inputFile: String?, outputFile: String?) {
    // 단순 파서: --input PATH, --output PATH 추출
    var cmd = ""
    var params: [String] = []
    var inFile: String? = nil
    var outFile: String? = nil
    var i = 1
    while i < args.count {
        let a = args[i]
        if a == "--input" && i + 1 < args.count { inFile = args[i+1]; i += 2; continue }
        if a == "--output" && i + 1 < args.count { outFile = args[i+1]; i += 2; continue }
        if cmd.isEmpty { cmd = a } else { params.append(a) }
        i += 1
    }
    return (cmd, params, inFile, outFile)
}

func main() -> Int32 {
    let argv = CommandLine.arguments
    guard argv.count >= 2 else {
        FileHandle.standardError.write("Usage: PhotoCleanup <delete|album-add> [--input FILE] [--output FILE] ...\n".data(using: .utf8)!)
        return 1
    }
    let parsed = parseFlags(argv)
    let cmd = parsed.cmd
    outputFilePath = parsed.outputFile

    if !requestAccess() {
        let msg = "권한 거부 — 시스템 설정 → 사진 → PhotoCleanup 허용\n"
        FileHandle.standardError.write(msg.data(using: .utf8)!)
        if let path = outputFilePath {
            try? "{\"error\":\"permission_denied\"}".write(toFile: path, atomically: true, encoding: .utf8)
        }
        return 2
    }

    var uuids: [String] = []

    switch cmd {
    case "delete":
        if let path = parsed.inputFile {
            uuids = readUuidsFromFile(path)
        } else if !parsed.params.isEmpty {
            uuids = parsed.params
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
        guard parsed.params.count >= 1 else {
            FileHandle.standardError.write(
                "Usage: PhotoCleanup album-add <album_name> [--input FILE | <UUID>...]\n".data(using: .utf8)!)
            return 1
        }
        let albumName = parsed.params[0]
        if let path = parsed.inputFile {
            uuids = readUuidsFromFile(path)
        } else {
            uuids = Array(parsed.params.dropFirst())
        }
        guard let album = findOrCreateAlbum(albumName) else {
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

    case "delete-by-meta":
        // 2026-05-08 P0-C: osxphotos 우회 — filename + ISO date 직접 매칭.
        guard let inFile = parsed.inputFile else {
            FileHandle.standardError.write(
                "Usage: PhotoCleanup delete-by-meta --input FILE [--output FILE]\n"
                    .data(using: .utf8)!)
            return 1
        }
        let entries = readMetaFromFile(inFile)
        if entries.isEmpty {
            emitJson(Result(command: "delete-by-meta", processed: 0,
                            not_found: 0, failed: 0, error: "empty_input"))
            return 0
        }
        let assets = findAssetsByMeta(entries)
        let notFound = entries.count - assets.count
        let (deleted, err) = assets.isEmpty ? (0, nil) : deleteAssets(assets)
        emitJson(Result(command: "delete-by-meta", processed: deleted,
                        not_found: notFound,
                        failed: assets.count - deleted, error: err))
        return assets.count - deleted > 0 ? 1 : 0

    default:
        FileHandle.standardError.write("Unknown command: \(cmd)\n".data(using: .utf8)!)
        return 1
    }
}

exit(main())
