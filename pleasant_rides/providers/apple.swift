// Prints Apple Maps cycling routes as JSON: [{"name": ..., "advisories": [...], "points": [[lat, lon], ...]}, ...]
// Usage: apple ORIGIN_LAT ORIGIN_LON DEST_LAT DEST_LON
import Foundation
import MapKit

let args = CommandLine.arguments.dropFirst().compactMap(Double.init)
guard args.count == 4 else {
    FileHandle.standardError.write("usage: apple ORIGIN_LAT ORIGIN_LON DEST_LAT DEST_LON\n".data(using: .utf8)!)
    exit(2)
}

func mapItem(_ lat: Double, _ lon: Double) -> MKMapItem {
    MKMapItem(location: CLLocation(latitude: lat, longitude: lon), address: nil)
}

let request = MKDirections.Request()
request.source = mapItem(args[0], args[1])
request.destination = mapItem(args[2], args[3])
request.transportType = .cycling
request.requestsAlternateRoutes = true

do {
    let response = try await MKDirections(request: request).calculate()
    let routes = response.routes.map { route -> [String: Any] in
        let polyline = route.polyline
        var coords = [CLLocationCoordinate2D](repeating: kCLLocationCoordinate2DInvalid, count: polyline.pointCount)
        polyline.getCoordinates(&coords, range: NSRange(location: 0, length: polyline.pointCount))
        return [
            // e.g. "NY-9D", the main road taken
            "name": route.name,
            // e.g. "Bike paths and main roads", "May require walking."
            "advisories": route.advisoryNotices,
            "points": coords.map { [$0.latitude, $0.longitude] },
        ]
    }
    FileHandle.standardOutput.write(try JSONSerialization.data(withJSONObject: routes))
} catch {
    FileHandle.standardError.write("\(error)\n".data(using: .utf8)!)
    exit(1)
}
