/** 주·태스크 본문. 접혀 있고, 펴면 「확인」 항목이 보인다 (SPEC §2.2).
 *
 * 티켓 본문은 패널에서 통째로 보여 주지만 (`TicketDetail`), 주·태스크는 보드
 * 안에 산다. 늘 펴 두면 티켓이 안 보이고, 아예 안 보이면 적어 둔 뜻이 없다.
 */
export function BodyNote({ body, label }: { body: string | null; label: string }) {
  const text = (body ?? "").trim();
  if (!text) return null;
  return (
    <details className="body-note">
      <summary>{label}</summary>
      <pre>{text}</pre>
    </details>
  );
}
