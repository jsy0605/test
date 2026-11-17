import assert from 'node:assert/strict';
import { buildRoute, gallery, galleryMap, waypoints, artworkZones } from '../static/js/gallery-map.js';

const artworks = ['art-01', 'art-02', 'art-03', 'art-04'];
const obstacle = gallery.obstacle;
let checked = 0;

// 모든 선택 조합·방문 순서가 벽이나 중앙 장애물을 관통하지 않는지 검사합니다.
function visit(remaining, order = []) {
  if (order.length) {
    const route = buildRoute(order);
    assert.deepEqual(route[0], gallery.scan);
    assert.deepEqual(route.at(-1), gallery.scan);
    // x/y 좌표계에서 시계 방향 회전의 부호 있는 면적은 음수입니다.
    const twiceArea = route.slice(1).reduce((sum, b, index) => {
      const a = route[index]; return sum + a[0] * b[1] - b[0] * a[1];
    }, 0);
    assert(twiceArea < 0, `반시계 경로: ${order}`);
    for (let i = 1; i < route.length; i++) {
      const a = route[i - 1], b = route[i];
      if (a[1] === b[1] && a[1] < obstacle.y) assert(b[0] <= a[0], '아래 통로는 왼쪽으로만 진행');
      if (a[1] === b[1] && a[1] > obstacle.y + obstacle.height) assert(b[0] >= a[0], '위 통로는 오른쪽으로만 진행');
      if (a[0] === b[0] && a[0] < obstacle.x) assert(b[1] >= a[1], '왼쪽 통로는 위쪽으로만 진행');
      if (a[0] === b[0] && a[0] > obstacle.x + obstacle.width) assert(b[1] <= a[1], '오른쪽 통로는 아래쪽으로만 진행');
      for (let step = 0; step <= 100; step++) {
        const x = a[0] + (b[0] - a[0]) * step / 100;
        const y = a[1] + (b[1] - a[1]) * step / 100;
        assert(x > 0 && x < gallery.width && y > 0 && y < gallery.height);
        assert(!(x > obstacle.x && x < obstacle.x + obstacle.width
          && y > obstacle.y && y < obstacle.y + obstacle.height), `장애물 관통: ${order}`);
      }
    }
    checked++;
  }
  for (const id of remaining) visit(remaining.filter(item => item !== id), [...order, id]);
}

visit(artworks);
assert.equal(checked, 64);
assert.deepEqual(buildRoute([]), []);
assert.deepEqual(buildRoute(['art-04']).slice(0, 3), [gallery.scan, waypoints.right, waypoints.lowerRight], '작품4만 선택해도 아래 통로로 출발');
assert(buildRoute(['art-01']).some(p => p[0] === waypoints['art-04'][0] && p[1] === waypoints['art-04'][1]), '작품1 이후에도 역행 없이 위 통로로 복귀');
assert.throws(() => buildRoute(['art-05']));
assert.throws(() => buildRoute(['art-01', 'art-01']));
const svg = galleryMap([...artworks].reverse());
assert(svg.includes('작품 1 → 2 → 3 → 4'));
assert(svg.includes('시계 방향'));
assert(svg.includes('키오스크'));
assert.equal(gallery.kiosk[0], gallery.width);
assert(waypoints['art-01'][0] > waypoints['art-02'][0]);
assert.equal(artworkZones[0].wall[1], 0);
assert.equal(artworkZones[1].wall[1], 0);
assert.equal(artworkZones[2].wall[0], 0);
assert.equal(artworkZones[3].wall[1], gallery.height);
assert(gallery.width > gallery.height);
console.log(`지도 경로 검증 완료: ${checked}개 방문 조합, 시계 방향 고정, 스캔 지점 복귀 및 장애물 비관통 확인`);
