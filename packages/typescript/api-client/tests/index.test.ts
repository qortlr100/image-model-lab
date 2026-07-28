import { describe, expect, it } from "vitest";

import { PACKAGE_NAME } from "../src/index.js";

describe("api-client package", () => {
  it("exports a stable package name", () => {
    expect(PACKAGE_NAME).toBe("@image-model-lab/api-client");
  });
});
