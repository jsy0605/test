// 사진을 기준으로 재배치한 안내용 평면도입니다. Nav2 목표 좌표와는 별개입니다.
export const gallery = {
  width: 5.7,
  height: 3,
  obstacle: { x: 1.5, y: 1, width: 2.7, height: 1 },
  scan: [5.12, 1.5],
  kiosk: [5.7, 1.5],
};

export const waypoints = {
  scan: gallery.scan,
  right: [4.95, 1.5],
  lowerRight: [4.95, 0.55],
  'art-01': [4.15, 0.55],
  'art-02': [2, 0.55],
  lowerLeft: [0.55, 0.55],
  'art-03': [0.55, 1.5],
  upperLeft: [0.55, 2.45],
  'art-04': [1.65, 2.45],
  upperRight: [4.95, 2.45],
};
// 오른쪽 키오스크에서 아래 → 왼쪽 → 위 → 오른쪽으로 한 바퀴 돕니다.
// 선택하지 않은 작품 구역은 통과만 하며, 정차 목록에는 포함하지 않습니다.
const clockwiseCircuit = [
  'scan', 'right', 'lowerRight', 'art-01', 'art-02', 'lowerLeft',
  'art-03', 'upperLeft', 'art-04', 'upperRight', 'right', 'scan',
];
export const artworkZones = [
  { id: 'art-01', wall: [4.15, 0], rotation: 0, label: [4.15, -0.34] },
  { id: 'art-02', wall: [2, 0], rotation: 0, label: [2, -0.34] },
  { id: 'art-03', wall: [0, 1.5], rotation: 90, label: [-0.34, 1.5] },
  { id: 'art-04', wall: [1.65, 3], rotation: 180, label: [1.65, 3.24] },
];
const artworkIds = artworkZones.map(zone => zone.id);

function clockwiseArtworkOrder(ids) {
  if (ids.some(id => !artworkIds.includes(id)) || new Set(ids).size !== ids.length) {
    throw new Error('지도에 등록된 작품 1·2·3·4만 경로에 사용할 수 있어요.');
  }
  return artworkIds.filter(id => ids.includes(id));
}

export function buildRoute(ids) {
  clockwiseArtworkOrder(ids);
  return ids.length ? clockwiseCircuit.map(id => [...waypoints[id]]) : [];
}

const project = ([x, y]) => [58 + x * 100, 55 + (gallery.height - y) * 100];
const point = p => project(p).map(n => Number(n.toFixed(2))).join(',');

export function galleryMap(ids, active = -1) {
  return `<div class="gallery-map floor-plan">
    <svg viewBox="0 0 720 420" role="img" aria-labelledby="gallery-map-title gallery-map-description">
      <title id="gallery-map-title">작품 구역과 키오스크 위치</title>
      <desc id="gallery-map-description">선택한 작품을 진한 녹색으로 표시합니다.</desc>
      <defs>
        <pattern id="floor-grid-small" width="10" height="10" patternUnits="userSpaceOnUse"><path d="M10 0H0V10" fill="none" stroke="#e9ecdf" stroke-width=".5"/></pattern>
        <pattern id="floor-grid" width="50" height="50" patternUnits="userSpaceOnUse"><rect width="50" height="50" fill="url(#floor-grid-small)"/><path d="M50 0H0V50" fill="none" stroke="#dee4d2" stroke-width=".6"/></pattern>
        <pattern id="obstacle-hatch" width="8" height="8" patternUnits="userSpaceOnUse" patternTransform="rotate(45)"><rect width="8" height="8" fill="#e5e9dc"/><path d="M0 0V8" stroke="#d6deca" stroke-width="2"/></pattern>
      </defs>
      <rect x="58" y="55" width="570" height="300" fill="#f6f8ee"/>
      <rect x="58" y="55" width="570" height="300" fill="url(#floor-grid)" stroke="#7d8e6f" stroke-width="2.3"/>
      <rect x="208" y="155" width="270" height="100" fill="url(#obstacle-hatch)" stroke="#8f9f7b" stroke-width="1.7"/>
      <text x="343" y="202" text-anchor="middle" class="obstacle-label">중앙 장애물</text>
      <text x="343" y="220" text-anchor="middle" class="obstacle-size">작품 구역을 따라 둘러가요</text>
      ${artworkZones.map((zone, i) => {
        const index = ids.indexOf(zone.id);
        const chosen = index >= 0;
        const color = active >= 0 && active === index ? '#ce7951' : chosen ? '#526e43' : '#a7b29a';
        return `<g class="map-artwork-zone" data-zone="${i + 1}" transform="translate(${point(zone.wall)}) rotate(${zone.rotation})"><path d="M-57 0 A57 57 0 0 1 57 0Z" fill="${color}" fill-opacity="${chosen ? '.13' : '.05'}" stroke="${color}" stroke-width="1.8"/><path d="M-22 0H22" stroke="${color}" stroke-width="5" stroke-linecap="round"/></g>`;
      }).join('')}
      <g transform="translate(${point(gallery.kiosk)})"><path d="M0-58 A58 58 0 0 0 0 58Z" fill="#eee7f2" fill-opacity=".7" stroke="#b3a0c4" stroke-width="1.7" stroke-dasharray="4 4"/></g>
      ${artworkZones.map((zone, i) => {
        const [x, y] = project(waypoints[zone.id]);
        const [lx, ly] = project(zone.label);
        const index = ids.indexOf(zone.id);
        const chosen = index >= 0;
        const color = active >= 0 && active === index ? '#ce7951' : chosen ? '#526e43' : '#a7b29a';
        return `<g class="map-artwork" data-artwork-id="${zone.id}" fill="${color}"><title>작품 ${i + 1}${chosen ? ' · 선택됨' : ' · 선택 전'}</title><text x="${lx}" y="${ly}" text-anchor="middle" class="map-artwork-label">작품 ${i + 1}</text><circle cx="${x}" cy="${y}" r="13" fill="${color}" stroke="#fbfcf6" stroke-width="2"/><text x="${x}" y="${y + 4}" text-anchor="middle" fill="white" font-size="12">${i + 1}</text></g>`;
      }).join('')}
      <g transform="translate(${point(gallery.scan)})" class="map-scan"><circle r="10" fill="#a58ab8" stroke="#fbfcf6" stroke-width="2"/></g>
      <g transform="translate(${point(gallery.kiosk)})" class="map-scan"><rect x="-10" y="-17" width="20" height="25" rx="3" fill="#a58ab8"/><path d="M-5-11H5M-5-6H3M0 8v6m-6 0H6" stroke="#f8f5fb" stroke-width="1.5"/><text x="42" y="-3" text-anchor="middle">키오스크</text><text x="42" y="13" text-anchor="middle">스캔 지점</text></g>
    </svg>
    <div class="map-key"><span><i class="map-dot green"></i> 작품 구역 · 숫자는 작품 인덱스</span><span><i class="map-dot purple"></i> 키오스크 스캔</span></div>
  </div>`;
}
