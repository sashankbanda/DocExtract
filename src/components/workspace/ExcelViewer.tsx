import { ScrollArea } from "@/components/ui/scroll-area";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { UploadFile } from "@/types/document";
import { FileSpreadsheet } from "lucide-react";
import { useEffect, useState } from "react";
import * as XLSX from "xlsx";

interface ExcelViewerProps {
  file: UploadFile;
}

export function ExcelViewer({ file }: ExcelViewerProps) {
  const [data, setData] = useState<any[][]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const loadExcel = async () => {
      if (!file.rawFile) return;
      
      setLoading(true);
      setError(null);
      
      try {
        const buffer = await file.rawFile.arrayBuffer();
        const workbook = XLSX.read(buffer, { type: "array" });
        const firstSheetName = workbook.SheetNames[0];
        const worksheet = workbook.Sheets[firstSheetName];
        const jsonData = XLSX.utils.sheet_to_json(worksheet, { header: 1 }) as any[][];
        setData(jsonData);
      } catch (err) {
        console.error("Error parsing Excel file:", err);
        setError("Failed to parse Excel file.");
      } finally {
        setLoading(false);
      }
    };

    loadExcel();
  }, [file]);

  if (loading) {
    return (
      <div className="flex items-center justify-center h-full text-muted-foreground">
        Parsing spreadsheet...
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex items-center justify-center h-full text-destructive">
        {error}
      </div>
    );
  }

  if (!data.length) {
    return (
      <div className="flex flex-col items-center justify-center h-full text-muted-foreground">
        <FileSpreadsheet className="w-12 h-12 mb-4 opacity-50" />
        <p>No data found in spreadsheet</p>
      </div>
    );
  }

  return (
    <div className="h-full flex flex-col">
      <div className="p-4 border-b bg-muted/30">
        <h3 className="font-medium flex items-center gap-2">
          <FileSpreadsheet className="w-4 h-4" />
          {file.name}
        </h3>
      </div>
      <ScrollArea className="flex-1 w-full">
        <div className="p-4">
          <Table>
            <TableHeader>
              <TableRow>
                {data[0]?.map((header: any, index: number) => (
                  <TableHead key={index} className="font-bold">
                    {String(header || "")}
                  </TableHead>
                ))}
              </TableRow>
            </TableHeader>
            <TableBody>
              {data.slice(1).map((row, rowIndex) => (
                <TableRow key={rowIndex}>
                  {row.map((cell: any, cellIndex: number) => (
                    <TableCell key={cellIndex}>
                      {String(cell || "")}
                    </TableCell>
                  ))}
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      </ScrollArea>
    </div>
  );
}
