import assert from 'node:assert/strict';
import { courseSelection, selectedArtworks, sortedArtworks } from '../static/js/course-selection.js';

const artworks = [4, 2, 1, 3].map(index => ({
  id: `art-0${index}`, artwork_index: index, artwork_id: `00${index}`,
  title: `작품 ${index}`, title_en: `artwork${index}`, artist_name_en: `artist${index}`,
  location: `00${index}`, theme: `theme${index}`, description: `description${index}`,
}));
assert.deepEqual(sortedArtworks(artworks).map(art => art.artwork_index), [1, 2, 3, 4]);
assert.deepEqual(artworks.map(art => art.artwork_index), [4, 2, 1, 3]);
// 체크한 순서나 중복과 관계없이 기존 작품을 숫자 인덱스 순서대로 한 번씩 표시합니다.
assert.deepEqual(selectedArtworks(artworks, ['art-04', 'missing', 'art-01', 'art-04']).map(art => art.id), ['art-01', 'art-04']);
for (let mask = 0; mask < 16; mask++) {
  const ids = artworks.filter(art => mask & (1 << (art.artwork_index - 1))).map(art => art.id);
  const chosen = selectedArtworks(artworks, ids);
  const markup = courseSelection(artworks, ids);
  assert.equal((markup.match(/type="checkbox"/g) || []).length, 4);
  assert.equal((markup.match(/ checked/g) || []).length, chosen.length);
  assert.equal((markup.match(/class="route-artwork-id"/g) || []).length, chosen.length);
  const routeIds = [...markup.matchAll(/class="route-artwork-id">(\d+)</g)].map(match => match[1]);
  assert.deepEqual(routeIds, chosen.map(art => art.artwork_id));
  assert(markup.includes(`${chosen.length} / 4개 선택`));
}
const unselected = courseSelection(artworks, []);
assert(unselected.includes('작품을 선택하면 이곳에 관람 경로가 표시돼요.'));
assert(unselected.includes('data-action="select-all-artworks" >전체선택'));
const all = courseSelection(artworks, artworks.map(art => art.id));
assert(all.includes('data-action="select-all-artworks" disabled'));
assert(!all.includes('추천 코스') && !all.includes('키워드 코스'));
const malicious = courseSelection([{...artworks[0], title_en: '<img src=x onerror=alert(1)>', description: '<script>x</script>'}], []);
assert(!malicious.includes('<img') && !malicious.includes('<script>'));
assert(malicious.includes('&lt;img') && malicious.includes('&lt;script&gt;'));
console.log('작품 체크 목록 검증: 16개 선택 조합, 오름차순 경로, 전체선택 및 안전한 텍스트 출력');
