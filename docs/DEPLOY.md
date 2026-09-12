# 배포 (Windows + Cloudflare Tunnel)

컨테이너 하나가 API 와 프론트엔드를 같이 서빙한다. 오리진이 하나라
CORS · 쿠키 SameSite · OAuth 오리진을 두 곳에 맞출 일이 없다.

```
[브라우저] ──https──> [Cloudflare] ──터널──> [PC: app :8000] ──> [PC: db :5432]
```

**Docker Desktop 을 쓴다.** Windows 에 Python · Node · psql 을 깔 필요가 없고,
`orjson` 의 `.pyd` 가 스마트 앱 컨트롤에 막히는 문제(TODO §5)도 리눅스 컨테이너라
생기지 않는다.

## 1. .env

`.env.example` 을 `.env` 로 복사해 채운다. 반드시 채워야 하는 것:

| 변수 | 왜 |
|---|---|
| `SESSION_SECRET` | 비우면 **재시작마다 로그인이 풀린다.** `python -c "import secrets; print(secrets.token_urlsafe(32))"` |
| `ANTHROPIC_API_KEY` | 없으면 목업 Planner 로 돈다 (그래프는 그대로 돌지만 내용이 상투구다) |
| `TZ=Asia/Seoul` | 스케줄러가 00:10 · 00:20 · 09:00 에 도는데, 없으면 UTC 라 **9시간 밀린다** |
| `POSTGRES_PASSWORD` | 기본값 말고 바꾼다 |

`SESSION_COOKIE_SECURE=true` 로 둔다 — HTTPS 는 Cloudflare 가 종료해 준다.
로컬 `http://localhost:8000` 으로만 볼 때는 `false` 로 해야 쿠키가 실린다.

## 2. 띄운다

```powershell
docker compose up -d --build
```

- 뜰 때 **적용 안 된 마이그레이션만** 먹인다 (`scripts/migrate.sh`).
- DB 가 받을 준비될 때까지 앱이 기다린다 (healthcheck).
- `http://localhost:8000` 으로 먼저 확인한다.

어디까지 적용됐는지 보려면:

```powershell
docker compose exec app ./scripts/migrate.sh --status
```

**이력 테이블이 생기기 전에 만든 DB** 를 그대로 옮겨 왔다면 한 번만:

```powershell
docker compose exec app ./scripts/migrate.sh --baseline 0010
```

## 3. 터널

Cloudflare Zero Trust > Networks > Tunnels 에서 **named tunnel** 을 만들고 토큰을
`.env` 의 `CLOUDFLARE_TUNNEL_TOKEN` 에 넣는다. Public hostname 을 갖고 있는 도메인에
붙이고, 서비스는 `http://app:8000` 으로 준다 (compose 네트워크 안의 이름이다).

```powershell
docker compose --profile tunnel up -d
```

> ⚠ **Quick Tunnel(`cloudflared tunnel --url`)은 쓰지 않는다.**
> GET 으로 오는 SSE 가 버퍼링돼 연결이 닫힐 때 이벤트가 한꺼번에 오는
> [열린 이슈](https://github.com/cloudflare/cloudflared/issues/1449)가 있다.
> 이 앱의 생성 진행 로그가 정확히 `GET /projects/{id}/stream` 이다.

### 터널을 붙인 직후 이것부터 확인한다

로드맵 생성을 눌러 **진행 로그가 한 줄씩 올라오는지** 본다. 끝나고 한꺼번에 뜨면
버퍼링에 걸린 것이다 — 그러면 폴링으로 바꾸거나 스트림을 POST 로 옮겨야 한다.
다른 걸 붙이기 전에 이걸 먼저 본다.

## 4. Windows 에서 따로 챙길 것

- **절전·최대 절전을 끈다.** 자면 APScheduler 가 멈추고 실패 감지가 죽는다.
  모니터만 꺼지게 둔다. (설정 > 시스템 > 전원 > 화면 및 절전)
- **Docker Desktop 을 로그인 시 자동 시작**으로 둔다. `restart: unless-stopped` 가
  컨테이너는 살리지만, Docker 자체가 안 떠 있으면 의미가 없다.
- 구글 로그인을 쓰려면 승인된 JavaScript 원본에 터널 도메인을 넣는다.
  **`GOOGLE_CLIENT_ID` 가 들어오는 순간 데모 로그인 문이 닫힌다.**

## 5. 다른 호스팅으로 옮길 때

같은 이미지가 그대로 돈다. `DATABASE_URL` 만 그쪽 Postgres 로 바꾸면 된다 —
스키마가 순수 Postgres 라서(`pgcrypto` · `gen_random_uuid`) Supabase 여도, 관리형
Postgres 여도 상관없다. 후보와 가격 비교는 `TODO.md` §14 에 있다.

**과제 제출처럼 「공개 URL 이 떠 있어야」 하는 상황에는 PC 를 쓰지 않는다.**
기계가 꺼져 있거나 집 인터넷이 끊긴 순간에 열면 그걸로 끝이다.

## 로그 보기

```powershell
docker compose logs -f app
```

LLM 호출마다 이런 줄이 남는다 — 이게 실제 비용의 근거다 (`TODO.md` §13):

```
llm DecomposeResult model=claude-sonnet-5 in=1234 out=15678 cache_write=0 cache_read=0 stop=end_turn
```
