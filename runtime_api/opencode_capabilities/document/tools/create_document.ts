import { tool } from "@opencode-ai/plugin"
import { rm, writeFile } from "node:fs/promises"
import path from "node:path"

export default tool({
  description: "Render and validate an editable DOCX from a structured Nomi document specification.",
  args: {
    title: tool.schema.string().describe("Document title."),
    subtitle: tool.schema.string().optional(),
    audience: tool.schema.string().describe("Intended reader."),
    purpose: tool.schema.string().describe("Outcome the document must support."),
    author: tool.schema.string().optional(),
    sections: tool.schema.array(tool.schema.object({
      kind: tool.schema.enum(["executive_summary", "analysis", "narrative", "table", "recommendations", "appendix"]),
      heading: tool.schema.string(),
      level: tool.schema.number().int().min(1).max(3),
      paragraphs: tool.schema.array(tool.schema.string()).optional(),
      bullets: tool.schema.array(tool.schema.string()).optional(),
      numbered_items: tool.schema.array(tool.schema.string()).optional(),
      table: tool.schema.object({
        headers: tool.schema.array(tool.schema.string()).min(1),
        rows: tool.schema.array(tool.schema.array(tool.schema.string())),
      }).optional(),
      source_evidence_ids: tool.schema.array(tool.schema.string()),
    })).min(1),
    filename: tool.schema.string().describe("Safe output filename ending in .docx."),
  },
  async execute(args, context) {
    const { filename, ...specification } = args
    const specPath = path.join(context.directory, "nomi_document_spec.json")
    const outputPath = path.join(context.directory, filename)
    const manifestPath = process.env.NOMI_ARTIFACT_MANIFEST || path.join(context.directory, "nomi_artifact_manifest.json")
    const scriptsDir = process.env.NOMI_RUNTIME_SCRIPTS_DIR || "/app/scripts"
    const pythonExecutable = process.env.NOMI_PYTHON_EXECUTABLE || "python"
    const rendererPath = path.join(scriptsDir, "nomi_document_tool.py")
    await rm(manifestPath, { force: true })
    await rm(outputPath, { force: true })
    await writeFile(specPath, JSON.stringify(specification, null, 2), "utf8")
    const result = await Bun.$`${pythonExecutable} ${rendererPath} --spec ${specPath} --output ${outputPath} --manifest ${manifestPath} --packet ${process.env.NOMI_OPENCODE_STEP_PACKET || ""}`.nothrow().quiet()
    const stdout = result.stdout.toString().trim()
    const stderr = result.stderr.toString().trim()
    if (result.exitCode !== 0) {
      return JSON.stringify({ status: "failed", exit_code: result.exitCode, error: stderr || stdout || "document renderer failed" })
    }
    return stdout
  },
})
