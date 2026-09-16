/** @input Fetch and server API. @output Authenticated requests and shared types. @position API adapter. @doc-sync Update INDEX.md on changes. */
export type Json = Record<string, any>;
export interface Resource {
  id: string;
  kind: string;
  name: string;
  description: string;
  content: string;
  config: Json;
  enabled: boolean;
  version: number;
  has_secret?: boolean;
  parent_id?: string;
}
let csrf = "";
export function setCsrf(value: string) {
  csrf = value;
}
export async function api<T = any>(
  path: string,
  method = "GET",
  data?: unknown,
): Promise<T> {
  const form = data instanceof FormData;
  const response = await fetch("/api/v1" + path, {
    method,
    credentials: "include",
    headers: {
      ...(form ? {} : { "Content-Type": "application/json" }),
      "X-CSRF-Token": csrf,
    },
    body: data === undefined ? undefined : form ? data : JSON.stringify(data),
  });
  const result = await response.json();
  if (!response.ok)
    throw new Error(
      typeof result.detail === "string"
        ? result.detail
        : JSON.stringify(result.detail || result),
    );
  return result;
}
export const list = (kind: string) => api<Resource[]>("/resources/" + kind);
export const labels: Record<string, string> = {
  QUEUED: "排队中",
  RUNNING: "执行中",
  SUCCEEDED: "已完成",
  FAILED: "失败",
  PAUSED: "已暂停",
  BLOCKED: "已阻塞",
  CANCELLED: "已取消",
  WAITING_APPROVAL: "等待确认",
  PAUSE_REQUESTED: "正在暂停",
  CANCEL_REQUESTED: "正在取消",
  NEEDS_REVIEW: "需要核查",
  UNKNOWN: "结果未知",
  PENDING: "待审核",
  STARTING: "启动中",
  STOPPED: "已停止",
  APPROVED: "已允许",
  REJECTED: "已拒绝",
};
export const date = (value: number) => new Date(value).toLocaleString("zh-CN");
