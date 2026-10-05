// 用 macOS 內建的 Vision 辨識優惠券圖片上的文字。
// 用法：ocr 圖1 圖2 …
// 每張圖輸出一行 JSON：
//   {"file": 路徑, "orange": 右上角橘色比例,
//    "lines": [{"t": 最可能的文字, "alts": [前幾個候選], "pass": "orig"|"green",
//               "x","y","w","h": 位置（0~1，左上為原點）}]}
// 每張圖辨識兩次（原圖、只取綠色通道），因為紅色折扣數字和黑色數字各在不同版本比較好認；
// 哪個讀法才對，交給 Python 用「原價 − 折扣 = 售價」驗算決定。
import CoreImage
import Foundation
import Vision

// 只取綠色通道轉成灰階：紅字在綠色通道裡是深色
func greenChannel(_ img: CIImage) -> CIImage {
    let g = CIVector(x: 0, y: 1, z: 0, w: 0)
    return img.applyingFilter("CIColorMatrix", parameters: [
        "inputRVector": g, "inputGVector": g, "inputBVector": g,
    ])
}

// 「僅限好市多線上購物」的券右上角有橘色標籤（實測約 0.41），賣場券是 0。
// 文字辨識常漏讀「【賣場售價】」小字，用顏色判斷比較穩。
func orangeRatio(_ img: CIImage) -> Double {
    let e = img.extent
    let crop = CGRect(x: e.minX + e.width * 0.62, y: e.minY + e.height * 0.86,
                      width: e.width * 0.38, height: e.height * 0.14)
    let w = 40, h = 14
    let part = img.cropped(to: crop)
        .transformed(by: CGAffineTransform(translationX: -crop.minX, y: -crop.minY))
        .transformed(by: CGAffineTransform(scaleX: CGFloat(w) / crop.width, y: CGFloat(h) / crop.height))
    var buf = [UInt8](repeating: 0, count: w * h * 4)
    CIContext().render(part, toBitmap: &buf, rowBytes: w * 4,
                       bounds: CGRect(x: 0, y: 0, width: w, height: h), format: .RGBA8,
                       colorSpace: CGColorSpace(name: CGColorSpace.sRGB))
    var n = 0
    for i in stride(from: 0, to: buf.count, by: 4) {
        let r = buf[i], g = buf[i + 1], b = buf[i + 2]
        if r > 200 && g > 80 && g < 180 && b < 90 { n += 1 }
    }
    return Double(n) / Double(w * h)
}

func recognize(_ img: CIImage, pass: String) -> [[String: Any]] {
    var lines: [[String: Any]] = []
    let req = VNRecognizeTextRequest { req, _ in
        for obs in (req.results as? [VNRecognizedTextObservation]) ?? [] {
            let cands = obs.topCandidates(3)
            guard let top = cands.first else { continue }
            let b = obs.boundingBox  // Vision 的原點在左下，轉成左上
            lines.append([
                "t": top.string, "alts": cands.map { $0.string }, "pass": pass,
                "x": b.minX, "y": 1 - b.maxY, "w": b.width, "h": b.height,
            ])
        }
    }
    req.recognitionLevel = .accurate
    req.recognitionLanguages = ["zh-Hant", "en-US"]
    req.usesLanguageCorrection = false  // 數字不要被「校正」成單字
    do {
        try VNImageRequestHandler(ciImage: img, options: [:]).perform([req])
    } catch {
        FileHandle.standardError.write("辨識失敗（\(pass)）：\(error)\n".data(using: .utf8)!)
    }
    return lines
}

for path in CommandLine.arguments.dropFirst() {
    var lines: [[String: Any]] = []
    var orange = 0.0
    if let img = CIImage(contentsOf: URL(fileURLWithPath: path)) {
        lines = recognize(img, pass: "orig") + recognize(greenChannel(img), pass: "green")
        orange = orangeRatio(img)
    } else {
        FileHandle.standardError.write("讀不到圖片：\(path)\n".data(using: .utf8)!)
    }
    let out: [String: Any] = ["file": path, "orange": orange, "lines": lines]
    let data = try! JSONSerialization.data(withJSONObject: out, options: [.sortedKeys])
    print(String(data: data, encoding: .utf8)!)
}
