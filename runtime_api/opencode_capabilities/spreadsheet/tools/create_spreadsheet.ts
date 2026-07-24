import { tool } from "@opencode-ai/plugin"
import { rm, writeFile } from "node:fs/promises"
import path from "node:path"

export default tool({
  description: "Render and validate an editable XLSX from a structured Nomi spreadsheet specification.",
  args: {
    title: tool.schema.string().describe("Workbook title."),
    purpose: tool.schema.string().describe("Decision or analysis question answered by the workbook."),
    locale: tool.schema.string().optional(),
    currency: tool.schema.string().optional(),
    sheets: tool.schema.array(tool.schema.object({
      name: tool.schema.string().describe("Excel-safe unique sheet name."),
      description: tool.schema.string().optional(),
      columns: tool.schema.array(tool.schema.object({
        key: tool.schema.string(),
        label: tool.schema.string(),
        type: tool.schema.enum(["text", "integer", "number", "currency", "percentage", "date", "datetime", "boolean", "formula"]),
        formula: tool.schema.string().optional().describe("A1 formula template using {row}, for formula columns only."),
        result_type: tool.schema.enum(["integer", "number", "currency", "percentage"]).optional().describe("Visible result format for formula columns."),
      })).min(1),
      rows: tool.schema.array(
        tool.schema.record(
          tool.schema.string(),
          tool.schema.union([tool.schema.string(), tool.schema.number(), tool.schema.boolean(), tool.schema.null()]),
        ),
      ),
      source_evidence_ids: tool.schema.array(tool.schema.string()),
    })).min(1),
    filename: tool.schema.string().describe("Safe output filename ending in .xlsx."),
  },
  async execute(args, context) {
    const { filename, ...specification } = args
    const specPath = path.join(context.directory, "nomi_spreadsheet_spec.json")
    const outputPath = path.join(context.directory, filename)
    const manifestPath = process.env.NOMI_ARTIFACT_MANIFEST || path.join(context.directory, "nomi_artifact_manifest.json")
    const scriptsDir = process.env.NOMI_RUNTIME_SCRIPTS_DIR || "/app/scripts"
    const pythonExecutable = process.env.NOMI_PYTHON_EXECUTABLE || "python"
    const rendererPath = path.join(scriptsDir, "nomi_spreadsheet_tool.py")
    await rm(manifestPath, { force: true })
    await rm(outputPath, { force: true })
    await writeFile(specPath, JSON.stringify(specification, null, 2), "utf8")
    const result = await Bun.$`${pythonExecutable} ${rendererPath} --spec ${specPath} --output ${outputPath} --manifest ${manifestPath} --packet ${process.env.NOMI_OPENCODE_STEP_PACKET || ""}`.nothrow().quiet()
    const stdout = result.stdout.toString().trim()
    const stderr = result.stderr.toString().trim()
    if (result.exitCode !== 0) {
      return JSON.stringify({ status: "failed", exit_code: result.exitCode, error: stderr || stdout || "spreadsheet renderer failed" })
    }
    return stdout
  },
})
