import { describe, expect, it } from "vitest";
import {
  continuousSnappedWheelRotation,
  normalizedRotationPlaneBasis,
  rotationWheelDirectionSign,
  snappedRotationDelta,
  snappedWheelRotation,
} from "@/components/workplane/transformOverlayTypes";

describe("rotation handle projection", () => {
  it("preserves face-plane foreshortening while normalizing icon size", () => {
    expect(normalizedRotationPlaneBasis({ x: 10, y: 20, a: 2, b: 0, c: 0.5, d: 1 })).toEqual({
      a: 1,
      b: 0,
      c: 0.25,
      d: 0.5,
    });
  });

  it("turns an upper arrow upright without detaching it from the face plane", () => {
    expect(normalizedRotationPlaneBasis({ x: 10, y: 20, a: 2, b: 0, c: 0.5, d: 1 }, true)).toEqual({
      a: 1,
      b: 0,
      c: -0.25,
      d: -0.5,
    });
  });

  it("falls back to a screen-facing icon for a collapsed projection", () => {
    expect(normalizedRotationPlaneBasis({ x: 10, y: 20, a: 0, b: 0, c: 0, d: 0 })).toEqual({
      a: 1,
      b: 0,
      c: 0,
      d: 1,
    });
  });

  it("moves 45-degree rotation in the same screen direction as 22.5-degree rotation", () => {
    const direction = rotationWheelDirectionSign(1);
    expect(snappedWheelRotation(-52, -80, direction)).toEqual({ delta: -45, pointerAngle: -45 });
    expect(snappedWheelRotation(-58, -80, direction)).toEqual({ delta: -45, pointerAngle: -45 });
    expect(snappedWheelRotation(-69, -80, direction)).toEqual({ delta: 0, pointerAngle: -90 });
  });

  it("switches the wheel rotation and orange indicator to 22.5-degree marks with Shift", () => {
    const direction = rotationWheelDirectionSign(1);
    expect(snappedWheelRotation(-58, -80, direction, 22.5)).toEqual({ delta: -22.5, pointerAngle: -67.5 });
    expect(snappedWheelRotation(-52, -80, direction, 22.5)).toEqual({ delta: -45, pointerAngle: -45 });
  });

  it("keeps the current result continuous when switching to 22.5-degree snapping", () => {
    const direction = rotationWheelDirectionSign(1);
    const coarse = snappedWheelRotation(-58, -80, direction);
    const fineAtShift = continuousSnappedWheelRotation(
      snappedWheelRotation(-58, -80, direction, 22.5),
      22.5,
      45,
      coarse.delta,
      coarse.pointerAngle,
    );
    expect(fineAtShift).toEqual({
      delta: -45,
      pointerAngle: -45,
      deltaOffset: -22.5,
      pointerOffset: 22.5,
    });

    const fineForward = continuousSnappedWheelRotation(
      snappedWheelRotation(-52, -80, direction, 22.5),
      22.5,
      22.5,
      fineAtShift.delta,
      fineAtShift.pointerAngle,
      fineAtShift.deltaOffset,
      fineAtShift.pointerOffset,
    );
    expect(fineForward).toEqual({
      delta: -67.5,
      pointerAngle: -22.5,
      deltaOffset: -22.5,
      pointerOffset: 22.5,
    });
  });

  it("keeps one-degree rotation outside the wheel", () => {
    expect(snappedRotationDelta(28.4, false, false)).toBe(28);
  });

  it("retains the Shift 45-degree shortcut outside the wheel", () => {
    expect(snappedRotationDelta(28, false, true)).toBe(45);
  });

  it("keeps absolute wheel snapping synchronized when screen rotation is inverted", () => {
    expect(snappedWheelRotation(-134, -80, -1)).toEqual({ delta: 45, pointerAngle: -135 });
  });

  it("wraps wheel deltas across the -180/180 boundary", () => {
    expect(snappedWheelRotation(-179, 179)).toEqual({ delta: 0, pointerAngle: -180 });
    expect(snappedWheelRotation(-134, 179)).toEqual({ delta: 45, pointerAngle: -135 });
  });
});
