import { describe, expect, it } from "vitest";

import { SERVICE_INFO } from "../src/service-info";

describe("service info", () => {
  it("publishes the web identity and semantic version", () => {
    expect(SERVICE_INFO).toEqual({
      name: "web",
      version: "0.1.0",
    });
  });
});
