async function refreshFleet() {
  const body = document.getElementById("fleet-body");
  try {
    const response = await fetch("/api/fleet", {cache: "no-store", signal: AbortSignal.timeout(5000)});
    if (!response.ok) throw Error();
    const fleet = await response.json();
    const robots = Object.values(fleet);
    // 이전 서버도 배터리와 도크의 수신 만료를 적용해 반환한다.
    for (const robot of robots) {
      if (typeof robot.available !== "boolean") {
        robot.available = robot.dock === true && Number.isFinite(robot.battery) && robot.battery > 30;
      }
    }
    const available = robots.filter(robot => robot.available).length;
    const counts = {total: robots.length, moving: robots.filter(robot => robot.moving).length,
      available, unavailable: robots.length - available};
    for (const [key, count] of Object.entries(counts)) {
      document.getElementById("fleet-" + key).textContent = count;
    }
    const rows = Object.entries(fleet).map(([name, robot]) => {
      const row = document.createElement("tr");
      for (const value of [name, robot.battery == null ? "미확인" : robot.battery + "%",
        robot.dock == null ? "미확인" : robot.dock ? "도킹" : "미도킹",
        robot.available == null ? "미확인" : robot.available ? "가능" : "불가"]) {
        row.insertCell().textContent = value;
      }
      return row;
    });
    body.replaceChildren(...rows);
  } catch {
    document.querySelectorAll(".stats b[id^=fleet-]").forEach(card => { card.textContent = "—"; });
    body.replaceChildren();
    body.insertRow().insertCell().textContent = "상태 조회 실패";
  }
  setTimeout(refreshFleet, 1000);
}
refreshFleet();
