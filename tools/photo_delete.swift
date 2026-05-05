// photo_delete.swift — PhotoKit Framework 공식 API로 Photos.app 사진 삭제.
//
// AppleScript 우회 — macOS 업데이트 호환성 보장 (Apple 공식 API).
// PHAsset.localIdentifier 입력받아 Photos.app "최근 삭제됨"으로 이동.
//
// 빌드:
//   swift build -c release  (Swift Package)
//   또는 swiftc -O tools/photo_delete.swift -o tools/photo_delete
//
// 사용:
//   echo "UUID1\nUUID2\n..." | tools/photo_delete
//   tools/photo_delete UUID1 UUID2 ...
//
// 종료 코드:
//   0 — 모든 자산 삭제 성공
//   1 — 일부 fail (stderr에 fail 자산 출력)
//   2 — 권한 거부 또는 권한 미부여
//   3 — Photos.app 미동작
//
// 출력 (stdout, JSON 한 줄):
//   {"deleted": N, "not_found": M, "failed": K, "details": [{"uuid": "...", "result": "..."}]}

import Foundation
import Photos

// 권한 요청 (첫 실행 시 prompt)
func requestPhotoLibraryAccess() -> Bool {
    let status = PHPhotoLibrary.authorizationStatus(for: .readWrite)
    switch status {
    case .authorized, .limited:
        return true
    case .denied, .restricted:
        return false
    case .notDetermined:
        let semaphore = DispatchSemaphore(value: 0)
        var granted = false
        PHPhotoLibrary.requestAuthorization(for: .readWrite) { newStatus in
            granted = (newStatus == .authorized || newStatus == .limited)
            semaphore.signal()
        }
        semaphore.wait()
        return granted
    @unknown default:
        return false
    }
}

// PHAsset.localIdentifier로 PHAsset 검색 (단일 또는 정확 매칭)
func findAssets(localIdentifiers: [String]) -> [PHAsset] {
    let result = PHAsset.fetchAssets(
        withLocalIdentifiers: localIdentifiers,
        options: nil
    )
    var assets: [PHAsset] = []
    result.enumerateObjects { asset, _, _ in
        assets.append(asset)
    }
    return assets
}

// 자산 삭제 (Photos.app "최근 삭제됨"으로 이동)
func deleteAssets(_ assets: [PHAsset]) -> (success: Int, failed: Int, error: String?) {
    let semaphore = DispatchSemaphore(value: 0)
    var success = false
    var errorMsg: String? = nil

    PHPhotoLibrary.shared().performChanges({
        PHAssetChangeRequest.deleteAssets(assets as NSFastEnumeration)
    }, completionHandler: { ok, error in
        success = ok
        errorMsg = error?.localizedDescription
        semaphore.signal()
    })
    semaphore.wait()

    if success {
        return (assets.count, 0, nil)
    } else {
        return (0, assets.count, errorMsg)
    }
}

// JSON 출력
struct Result: Codable {
    let deleted: Int
    let not_found: Int
    let failed: Int
    let details: [Detail]
    struct Detail: Codable {
        let uuid: String
        let result: String
    }
}

// 메인
func main() -> Int32 {
    // stdin 또는 args
    var inputs: [String] = []
    if CommandLine.arguments.count > 1 {
        inputs = Array(CommandLine.arguments[1...])
    } else {
        while let line = readLine() {
            let trimmed = line.trimmingCharacters(in: .whitespaces)
            if !trimmed.isEmpty {
                inputs.append(trimmed)
            }
        }
    }

    if inputs.isEmpty {
        FileHandle.standardError.write("Usage: echo UUID | photo_delete  또는  photo_delete UUID1 UUID2 ...\n".data(using: .utf8)!)
        return 1
    }

    if !requestPhotoLibraryAccess() {
        FileHandle.standardError.write("권한 거부 — 시스템 설정 → 개인정보 보호 → 사진 → photo_delete 허용 필요\n".data(using: .utf8)!)
        return 2
    }

    let assets = findAssets(localIdentifiers: inputs)
    let foundIds = Set(assets.map { $0.localIdentifier })
    let notFound = inputs.filter { !foundIds.contains($0) }

    var details: [Result.Detail] = []
    var deleted = 0
    var failed = 0

    if !assets.isEmpty {
        let r = deleteAssets(assets)
        deleted = r.success
        failed = r.failed
        for asset in assets {
            details.append(Result.Detail(
                uuid: asset.localIdentifier,
                result: r.success > 0 ? "deleted" : "failed:\(r.error ?? "unknown")"
            ))
        }
    }
    for nf in notFound {
        details.append(Result.Detail(uuid: nf, result: "not_found"))
    }

    let result = Result(deleted: deleted, not_found: notFound.count,
                        failed: failed, details: details)
    let encoder = JSONEncoder()
    let data = try! encoder.encode(result)
    print(String(data: data, encoding: .utf8)!)

    return failed > 0 ? 1 : 0
}

exit(main())
