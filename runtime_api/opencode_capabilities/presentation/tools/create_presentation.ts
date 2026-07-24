import { tool } from "@opencode-ai/plugin"
import { rm, writeFile } from "node:fs/promises"
import path from "node:path"

export default tool({
  description: "Render and validate an editable PPTX from a structured Nomi presentation specification.",
  args: {
    title: tool.schema.string().describe("Deck title grounded in the goal and evidence."),
    subtitle: tool.schema.string().optional(),
    audience: tool.schema.string().describe("Intended audience."),
    purpose: tool.schema.string().describe("What the deck must help the audience understand or do."),
    desired_action: tool.schema.string().optional(),
    theme: tool.schema.string().optional(),
    slides: tool.schema.array(tool.schema.object({
      role: tool.schema.enum(["title", "section", "concept", "process", "comparison", "evidence", "closing"]),
      title: tool.schema.string(),
      subtitle: tool.schema.string().optional(),
      takeaway: tool.schema.string().optional(),
      preview_points: tool.schema.array(tool.schema.string()).optional(),
      points: tool.schema.array(tool.schema.string()).optional(),
      steps: tool.schema.array(tool.schema.string()).optional(),
      actions: tool.schema.array(tool.schema.string()).optional(),
      strengths: tool.schema.array(tool.schema.string()).optional(),
      limits: tool.schema.array(tool.schema.string()).optional(),
      visual: tool.schema.object({
        type: tool.schema.enum(["flow", "sequence", "cycle", "comparison"]).optional(),
        nodes: tool.schema.array(tool.schema.string()).optional(),
      }).optional(),
      left: tool.schema.object({
        label: tool.schema.string(),
        items: tool.schema.array(tool.schema.string()),
      }).optional(),
      right: tool.schema.object({
        label: tool.schema.string(),
        items: tool.schema.array(tool.schema.string()),
      }).optional(),
      source_evidence_ids: tool.schema.array(tool.schema.string()).describe("Evidence ids supporting this slide."),
    })).min(1),
    filename: tool.schema.string().describe("Safe output filename ending in .pptx."),
  },
  async execute(args, context) {
    const { filename, ...specification } = args
    const specPath = path.join(context.directory, "nomi_presentation_spec.json")
    const outputPath = path.join(context.directory, filename)
    const manifestPath = process.env.NOMI_ARTIFACT_MANIFEST || path.join(context.directory, "nomi_artifact_manifest.json")
    const scriptsDir = process.env.NOMI_RUNTIME_SCRIPTS_DIR || "/app/scripts"
    const pythonExecutable = process.env.NOMI_PYTHON_EXECUTABLE || "python"
    const rendererPath = path.join(scriptsDir, "nomi_presentation_tool.py")
    await rm(manifestPath, { force: true })
    await rm(outputPath, { force: true })
    await writeFile(specPath, JSON.stringify(specification, null, 2), "utf8")
    const result = await Bun.$`${pythonExecutable} ${rendererPath} --spec ${specPath} --output ${outputPath} --manifest ${manifestPath} --packet ${process.env.NOMI_OPENCODE_STEP_PACKET || ""}`.nothrow().quiet()
    const stdout = result.stdout.toString().trim()
    const stderr = result.stderr.toString().trim()
    if (result.exitCode !== 0) {
      return JSON.stringify({ status: "failed", exit_code: result.exitCode, error: stderr || stdout || "presentation renderer failed" })
    }
    return stdout
  },
})
