import fs from "node:fs/promises";
import { FileBlob, SpreadsheetFile } from "@oai/artifact-tool";

const source = "C:/Users/hk010/Downloads/26-충남사회경제네트워크(충사넷) (15).xlsx";
const outDir = "C:/Users/hk010/OneDrive/바탕 화면/OPENMOON_FRONT/OPENMOON_FRONT/spreadsheet_work";
const workbook = await SpreadsheetFile.importXlsx(await FileBlob.load(source));

console.log((await workbook.inspect({
  kind: "sheet",
  include: "id,name",
  maxChars: 4000,
})).ndjson);

const sheets = workbook.worksheets.items;
for (const sheet of sheets) {
  console.log((await workbook.inspect({
    kind: "region",
    sheetId: sheet.name,
    range: "A1:T28",
    maxChars: 12000,
  })).ndjson);
  console.log((await workbook.inspect({
    kind: "formula",
    sheetId: sheet.name,
    range: "A1:T28",
    maxChars: 6000,
    options: { maxResults: 100 },
  })).ndjson);
  const preview = await workbook.render({ sheetName: sheet.name, range: "A1:T28", scale: 1.5, format: "png" });
  await fs.writeFile(`${outDir}/preview-${sheets.indexOf(sheet)}.png`, new Uint8Array(await preview.arrayBuffer()));
}
