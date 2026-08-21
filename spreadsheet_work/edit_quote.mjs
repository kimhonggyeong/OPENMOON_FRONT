import fs from "node:fs/promises";
import { FileBlob, SpreadsheetFile } from "@oai/artifact-tool";

const source = "C:/Users/hk010/Downloads/26-영인면행정복지센터 (1).xlsx";
const outputDir = "C:/Users/hk010/OneDrive/바탕 화면/OPENMOON_FRONT/OPENMOON_FRONT/outputs/internal_columns";
const outputPath = `${outputDir}/26-영인면행정복지센터-제작원가-마진-일정.xlsx`;

const workbook = await SpreadsheetFile.importXlsx(await FileBlob.load(source));
const sheet = workbook.worksheets.getItem("0821_강희지");

const schedules = sheet.getRange("L14:L23").values;
const costs = sheet.getRange("T14:T23").values;
sheet.getRange("L13:N13").values = [["제작 원가", "마진", "일정"]];
sheet.getRange("L14:L23").values = costs;
for (let row = 14; row <= 23; row += 1) {
  sheet.getRange(`M${row}`).formulas = [[`=IF(OR(I${row}="",L${row}=""),"",I${row}-L${row})`]];
}
sheet.getRange("N14:N23").values = schedules;
sheet.getRange("T14:T23").clear({ applyTo: "contents" });

sheet.getRange("L13:N13").format = {
  fill: "#FFFFFF",
  font: { bold: true, color: "#111111" },
  horizontalAlignment: "center",
  verticalAlignment: "center",
  borders: { preset: "none" },
};
sheet.getRange("L14:L23").format = {
  numberFormat: "#,##0",
  horizontalAlignment: "right",
  verticalAlignment: "center",
  borders: { preset: "all", style: "thin", color: "#BFBFBF" },
};
sheet.getRange("M14:M23").format = {
  numberFormat: "#,##0",
  horizontalAlignment: "right",
  verticalAlignment: "center",
  borders: { preset: "all", style: "thin", color: "#BFBFBF" },
};
sheet.getRange("N14:N23").format = {
  horizontalAlignment: "left",
  verticalAlignment: "center",
  wrapText: true,
  borders: { preset: "all", style: "thin", color: "#BFBFBF" },
};
sheet.getRange("L:L").format.columnWidth = 14;
sheet.getRange("M:M").format.columnWidth = 14;
sheet.getRange("N:N").format.columnWidth = 32;

await fs.mkdir(outputDir, { recursive: true });
console.log((await workbook.inspect({
  kind: "table",
  sheetId: sheet.name,
  range: "I13:N23",
  include: "values,formulas",
  tableMaxRows: 20,
  tableMaxCols: 8,
  maxChars: 12000,
})).ndjson);
console.log((await workbook.inspect({
  kind: "match",
  searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A",
  options: { useRegex: true, maxResults: 100 },
  summary: "final formula error scan",
})).ndjson);

const preview = await workbook.render({ sheetName: sheet.name, range: "A1:N24", scale: 1.4, format: "png" });
await fs.writeFile(`${outputDir}/preview.png`, new Uint8Array(await preview.arrayBuffer()));
const output = await SpreadsheetFile.exportXlsx(workbook);
await output.save(outputPath);
console.log(outputPath);
