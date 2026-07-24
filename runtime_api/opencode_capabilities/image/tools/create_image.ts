import { tool } from "@opencode-ai/plugin"
import { rm, writeFile } from "node:fs/promises"
import path from "node:path"

const DEFAULT_CANVAS = {
  width: 1200,
  height: 1600,
  background: "#F8FAFC",
}

const DEFAULT_PALETTE = {
  ink: "#1E293B",
  muted: "#526071",
  accent: "#2563EB",
  highlight: "#D97706",
}

export default tool({
  description: "Render and validate a PNG information graphic. Every process step must be stated by cited evidence. Do not use emoji or unsupported commitments such as 立即, 始终, 确保, 保障, 保护, 安全, 删除, 不会离开, 合并返回, or 100%.",
  args: {
    title: tool.schema.string().max(80),
    subtitle: tool.schema.string().optional(),
    purpose: tool.schema.string(),
    audience: tool.schema.string(),
    visual_kind: tool.schema.enum(["infographic", "diagram", "social_card", "poster"]),
    blocks: tool.schema.array(tool.schema.object({
      kind: tool.schema.enum(["process", "callout", "metric", "list"]),
      heading: tool.schema.string(),
      body: tool.schema.string().optional(),
      value: tool.schema.string().optional(),
      items: tool.schema.array(tool.schema.string()).max(5).optional(),
      source_evidence_ids: tool.schema.array(tool.schema.string()),
    })).min(1).max(6),
    footer: tool.schema.string().optional(),
    filename: tool.schema.string().describe("Safe output filename ending in .png."),
  },
  async execute(args, context) {
    const { filename, ...content } = args
    const specification = {
      ...content,
      canvas: DEFAULT_CANVAS,
      palette: DEFAULT_PALETTE,
    }
    const specPath = path.join(context.directory, "nomi_image_spec.json")
    const outputPath = path.join(context.directory, filename)
    const manifestPath = process.env.NOMI_ARTIFACT_MANIFEST || path.join(context.directory, "nomi_artifact_manifest.json")
    const scriptsDir = process.env.NOMI_RUNTIME_SCRIPTS_DIR || "/app/scripts"
    const pythonExecutable = process.env.NOMI_PYTHON_EXECUTABLE || "python"
    const rendererPath = path.join(scriptsDir, "nomi_image_tool.py")
    await rm(manifestPath, { force: true })
    await rm(outputPath, { force: true })
    await writeFile(specPath, JSON.stringify(specification, null, 2), "utf8")
    const result = await Bun.$`${pythonExecutable} ${rendererPath} --spec ${specPath} --output ${outputPath} --manifest ${manifestPath} --packet ${process.env.NOMI_OPENCODE_STEP_PACKET || ""}`.nothrow().quiet()
    const stdout = result.stdout.toString().trim()
    const stderr = result.stderr.toString().trim()
    if (result.exitCode !== 0) {
      return JSON.stringify({ status: "failed", exit_code: result.exitCode, error: stderr || stdout || "image renderer failed" })
    }
    return stdout
  },
})
