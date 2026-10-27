// fake-api must load before src/api/client.ts, which binds fetch when it is created.
import "./fake-api";
import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

afterEach(() => {
  cleanup();
  document.body.innerHTML = "";
});
