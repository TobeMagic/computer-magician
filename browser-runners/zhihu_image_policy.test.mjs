import assert from "node:assert/strict";
import test from "node:test";

import { decideZhihuImagePublish } from "./zhihu_image_policy.mjs";

test("blocks publish when every body image failed", () => {
  const decision = decideZhihuImagePublish({
    requiredImages: 11,
    uploadedCount: 0,
    visibleCount: 0,
  });
  assert.equal(decision.applied, false);
  assert.equal(decision.imagePartial, false);
  assert.equal(decision.imageFailures, 11);
});

test("continues publish when at least one body image is visible", () => {
  const decision = decideZhihuImagePublish({
    requiredImages: 11,
    uploadedCount: 10,
    visibleCount: 10,
  });
  assert.equal(decision.applied, true);
  assert.equal(decision.imagePartial, true);
  assert.equal(decision.imageFailures, 1);
});

test("treats a full image set as complete", () => {
  const decision = decideZhihuImagePublish({
    requiredImages: 3,
    uploadedCount: 3,
    visibleCount: 3,
  });
  assert.equal(decision.applied, true);
  assert.equal(decision.imagePartial, false);
  assert.equal(decision.imageFailures, 0);
});
