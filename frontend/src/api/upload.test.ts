import { afterEach, describe, expect, it, vi } from "vitest";
import { uploadMedia } from "./upload";

afterEach(() => vi.unstubAllGlobals());

describe("media upload", () => {
  const file = () => new File(["sample"], "sample.mp4", { type: "video/mp4" });

  it("passes a large file through FormData without a client byte ceiling or whole-file read", async () => {
    const source = file();
    Object.defineProperty(source, "size", { value: 30 * 1024 ** 3 });
    const read = vi.spyOn(source, "arrayBuffer");
    const fetch = vi
      .fn()
      .mockResolvedValue(
        Response.json({ source_id: "saved", filename: source.name }),
      );
    vi.stubGlobal("fetch", fetch);
    expect(await uploadMedia(source)).toMatchObject({ source_id: "saved" });
    expect(fetch).toHaveBeenCalledTimes(1);
    const request = fetch.mock.calls[0][1];
    expect(request.body).toBeInstanceOf(FormData);
    expect(request.body.get("file").name).toBe("sample.mp4");
    expect(request.headers).toBeUndefined();
    expect(read).not.toHaveBeenCalled();
  });

  it("preserves the backend's disk-space explanation", async () => {
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValue(
          Response.json(
            { detail: "Insufficient free space to save the upload." },
            { status: 507 },
          ),
        ),
    );
    await expect(uploadMedia(file())).rejects.toMatchObject({
      message: "Insufficient free space to save the upload.",
      status: 507,
    });
  });

  it("reports a proxy limit even if the error response is HTML", async () => {
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValue(
          new Response("<html>too large</html>", { status: 413 }),
        ),
    );
    await expect(uploadMedia(file())).rejects.toMatchObject({
      message:
        "Upload rejected (HTTP 413). Check the server or reverse proxy upload limit.",
      status: 413,
    });
  });

  it("reports HTTP failures when an intermediary returns an empty body", async () => {
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValue(
          new Response(null, { status: 504, statusText: "Gateway Timeout" }),
        ),
    );
    await expect(uploadMedia(file())).rejects.toThrow(
      "HTTP 504 Gateway Timeout",
    );
  });

  it("explains a connection interruption without claiming the file was not saved", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockRejectedValue(new TypeError("Failed to fetch")),
    );
    await expect(uploadMedia(file())).rejects.toThrow(
      "refresh the source library before retrying",
    );
  });

  it("does not claim success when the response cannot identify the saved source", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(Response.json({})));
    await expect(uploadMedia(file())).rejects.toThrow(
      "did not confirm the saved source",
    );
  });
});
