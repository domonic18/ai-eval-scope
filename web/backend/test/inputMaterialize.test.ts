import { describe, expect, it } from "vitest"

import { isZip, materializeInline, materializeUpload } from "../src/infra/inputMaterialize"

describe("inputMaterialize", () => {
  it("detects zip magic → unit scope", () => {
    const zip = Buffer.from([0x50, 0x4b, 0x03, 0x04, 0, 0, 0, 0])
    const m = materializeUpload("unit.zip", zip)
    expect(m.scope).toBe("unit")
    expect(m.inputKind).toBe("upload")
  })

  it("non-zip → single scope", () => {
    const m = materializeUpload("lesson.md", Buffer.from("# hi"))
    expect(m.scope).toBe("single")
    expect(m.inputKind).toBe("upload")
  })

  it("rejects empty body", () => {
    expect(() => materializeUpload("x", Buffer.alloc(0))).toThrow(/empty/)
  })

  it("rejects oversize upload", () => {
    expect(() => materializeUpload("big.zip", Buffer.alloc(51 * 1024 * 1024))).toThrow(/max size/)
  })

  it("inline → single scope", () => {
    const m = materializeInline("a.md", "text content")
    expect(m.scope).toBe("single")
    expect(m.inputKind).toBe("inline")
    expect(m.bytes.toString("utf-8")).toBe("text content")
  })

  it("isZip magic byte check", () => {
    expect(isZip(Buffer.from([0x50, 0x4b]))).toBe(true)
    expect(isZip(Buffer.from("# x"))).toBe(false)
    expect(isZip(Buffer.alloc(0))).toBe(false)
  })
})
