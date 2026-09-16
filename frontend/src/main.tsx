/** @input React and application. @output Browser root. @position Entry point. @doc-sync Update INDEX.md on changes. */
import React from "react";
import ReactDOM from "react-dom/client";
import { ConfigProvider, App as AntApp } from "antd";
import zhCN from "antd/locale/zh_CN";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter } from "react-router-dom";
import App from "./App";
import "./style.css";
import "./shell.css";
const client = new QueryClient({
  defaultOptions: { queries: { retry: 1, refetchOnWindowFocus: false } },
});
ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <ConfigProvider
      locale={zhCN}
      theme={{
        token: {
          colorPrimary: "#3157d5",
          colorText: "#172033",
          colorTextSecondary: "#56627a",
          colorTextPlaceholder: "#63738a",
          colorTextDisabled: "#63738a",
          colorBgLayout: "#f6f8fb",
          borderRadius: 10,
          fontFamily: 'Inter, "Microsoft YaHei", system-ui, sans-serif',
        },
        components: {
          Button: { controlHeight: 38 },
          Input: { controlHeight: 40 },
          Select: { controlHeight: 40 },
        },
      }}
    >
      <AntApp>
        <QueryClientProvider client={client}>
          <BrowserRouter>
            <App />
          </BrowserRouter>
        </QueryClientProvider>
      </AntApp>
    </ConfigProvider>
  </React.StrictMode>,
);
