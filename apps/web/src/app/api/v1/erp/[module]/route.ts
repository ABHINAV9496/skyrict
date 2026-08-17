import type { NextRequest } from "next/server";
import { NextResponse } from "next/server";

import {
    crmData,
    financeData,
    reportsKpis,
    salesData,
    type TablePayload,
} from "@/lib/mock/erp";

export const dynamic = "force-dynamic";

const DATA: Record<string, TablePayload | { kpis: typeof reportsKpis }> = {
    crm: crmData,
    sales: salesData,
    finance: financeData,
    reports: { kpis: reportsKpis },
};

export async function GET(
    _request: NextRequest,
    { params }: { params: Promise<{ module: string }> },
) {
    const { module } = await params;
    const payload = DATA[module];
    if (!payload) {
        return NextResponse.json(
            { detail: "Unknown ERP module." },
            { status: 404 },
        );
    }
    return NextResponse.json({ data: payload });
}
