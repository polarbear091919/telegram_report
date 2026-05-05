-- 성공적으로 다운로드된 리포트
create table reports (
  id                bigserial primary key,
  message_id        bigint      not null,
  chat_username     text        not null,

  -- 시각 정보 (둘 다 UTC; 표시 시 'Asia/Seoul' 변환)
  sent_at           timestamptz not null,
  downloaded_at     timestamptz not null default now(),

  -- 파일 정보
  file_name         text        not null,
  file_path         text        not null,         -- STORAGE_BASE_DIR-relative (filename only in MVP)
  file_size_bytes   bigint      not null,
  file_hash_sha256  text        not null,

  -- 메시지 컨텍스트
  caption           text,

  -- 향후 태깅 워커가 채울 컬럼
  tags              text[],
  tagged_at         timestamptz,

  unique (chat_username, message_id)
);

-- 다운로드 실패한 메시지 (다음 실행에서 재시도 대상)
create table failed_attempts (
  id              bigserial primary key,
  message_id      bigint      not null,
  chat_username   text        not null,

  first_failed_at timestamptz not null default now(),
  last_failed_at  timestamptz not null default now(),
  attempt_count   int         not null default 1,
  error_message   text,

  unique (chat_username, message_id)
);

create index idx_reports_chat_msg on reports (chat_username, message_id desc);
create index idx_reports_sent_at  on reports (sent_at desc);
create index idx_reports_untagged on reports (tagged_at) where tagged_at is null;
create index idx_failed_chat on failed_attempts (chat_username, message_id);

-- RLS: 정책 없음 = anon/authenticated 거부. service_role은 우회.
alter table reports enable row level security;
alter table failed_attempts enable row level security;
