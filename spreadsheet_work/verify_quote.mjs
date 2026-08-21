import { FileBlob, SpreadsheetFile } from "@oai/artifact-tool";

const path = "C:/Users/hk010/OneDrive/바탕 화면/OPENMOON_FRONT/OPENMOON_FRONT/outputs/internal_columns/26-영인면행정복지센터-제작원가-마진-일정.xlsx";
const workbook = await SpreadsheetFile.importXlsx(await FileBlob.load(path));
console.log((await workbook.inspect({
  kind: "formula",
  sheetId: "0821_강희지",
  range: "L13:N23",
  maxChars: 8000,
  options: { maxResults: 30 },
})).ndjson);
