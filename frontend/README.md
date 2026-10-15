# frontend

QR AI Lab 的前端：Next.js 16（App Router、Cache Components）、React 19、Tailwind CSS v4、shadcn/ui、npm。

- 啟動與所有指令：見 [`../docs/GETTING_STARTED.md`](../docs/GETTING_STARTED.md)。
- 設計系統：[`../DESIGN.md`](../DESIGN.md)；token 實作在 `src/app/globals.css`。
- 目前資料來自 `src/lib/mock-data.ts`，統一經由 `src/lib/api/index.ts` 取用；接上 backend 時只改該檔。
- `AGENTS.md` 由 `next dev` 維護（Next.js 內建的 AI agent 說明），請一併提交。
