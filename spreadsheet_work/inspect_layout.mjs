import fs from "node:fs/promises";
import { FileBlob, SpreadsheetFile } from "@oai/artifact-tool";

const source = "C:/Users/hk010/Downloads/26-영인면행정복지센터 (1).xlsx";
const outDir = "C:/Users/hk010/OneDrive/바탕 화면/OPENMOON_FRONT/OPENMOON_FRONT/spreadsheet_work";
const workbook = await SpreadsheetFile.importXlsx(await FileBlob.load(source));
const sheet = workbook.worksheets.getItem("0821_강희지");
console.log((await workbook.inspect({ kind: "table", sheetId: sheet.name, range: "L13:T23", include: "values,formulas", maxChars: 10000, tableMaxRows: 20, tableMaxCols: 12 })).ndjson);
