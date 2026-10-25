import { describe, expect, it } from "vitest";
import { decode, project, roadPath } from "./geo";

describe("map geography", () => {
  it("reads OSRM's encoded road paths", () => {
    // The polyline format's own reference example.
    expect(decode("_p~iF~ps|U_ulLnnqC_mqNvxq`@")).toEqual([
      [38.5, -120.2],
      [40.7, -120.95],
      [43.252, -126.453],
    ]);
  });

  it("keeps the whole country inside the map, north up and east right", () => {
    const [tabukX, tabukY] = project(28.38, 36.57);
    const [jazanX, jazanY] = project(16.89, 42.57);
    const [gulfX] = project(26.5, 55.6); // the far east of the Gulf coast
    expect(tabukY).toBeLessThan(jazanY);
    expect(tabukX).toBeLessThan(jazanX);
    for (const v of [tabukX, tabukY, jazanX, jazanY, gulfX]) expect(v).toBeGreaterThan(0);
    expect(gulfX).toBeLessThan(620);
    expect(jazanY).toBeLessThan(490);
  });

  it("draws a road as one line through its points", () => {
    expect(roadPath([[24.7, 46.7], [26.4, 50.1]]).match(/[ML]/g)).toEqual(["M", "L"]);
  });
});
