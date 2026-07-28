import { SERVICE_INFO } from "./service-info";

export function App() {
  return (
    <main>
      <section aria-labelledby="service-title">
        <p className="eyebrow">Control plane</p>
        <h1 id="service-title">Image Model Lab</h1>
        <p className="summary">
          데이터셋, 학습 실행, ComfyUI 결과를 연결할 Web service skeleton입니다.
        </p>
        <dl>
          <div>
            <dt>Service</dt>
            <dd>{SERVICE_INFO.name}</dd>
          </div>
          <div>
            <dt>Version</dt>
            <dd>{SERVICE_INFO.version}</dd>
          </div>
          <div>
            <dt>Status</dt>
            <dd className="status">Ready</dd>
          </div>
        </dl>
        <p className="notice">
          제품 기능과 API 연결은 후속 vertical slice에서 추가됩니다.
        </p>
      </section>
    </main>
  );
}
