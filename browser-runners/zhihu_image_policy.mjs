export function decideZhihuImagePublish({ requiredImages = 0, uploadedCount = 0, visibleCount = 0 } = {}) {
  const required = Math.max(Number(requiredImages) || 0, 0);
  const shown = Math.max(Number(uploadedCount) || 0, Number(visibleCount) || 0);
  if (required > 0 && shown === 0) {
    return {
      applied: false,
      imagePartial: false,
      imageFailures: required,
    };
  }
  const missing = Math.max(0, required - shown);
  return {
    applied: true,
    imagePartial: missing > 0,
    imageFailures: missing,
  };
}
