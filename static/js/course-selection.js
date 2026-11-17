const escape = value => String(value ?? '').replace(/[&<>"']/g, char => ({
  '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
}[char]));

export const sortedArtworks = artworks => [...artworks].sort((a, b) => a.artwork_index - b.artwork_index);
export const selectedArtworks = (artworks, selectedIds) => sortedArtworks(artworks).filter(art => selectedIds.includes(art.id));

export function courseSelection(artworks, selectedIds) {
  const sorted = sortedArtworks(artworks);
  const chosen = selectedArtworks(artworks, selectedIds);
  return `<section class="artwork-selection" aria-labelledby="selection-heading">
    <div class="selection-toolbar"><div><h2 id="selection-heading">관람할 작품</h2><p id="selection-help">관람할 작품을 체크해 주세요.</p></div><div class="selection-actions"><span>${chosen.length} / ${sorted.length}개 선택</span><button type="button" class="button secondary" data-action="select-all-artworks" ${!sorted.length || chosen.length === sorted.length ? 'disabled' : ''}>전체선택</button><button type="button" class="selection-clear" data-action="clear-artworks" ${chosen.length ? '' : 'disabled'}>선택 해제</button></div></div>
    <div class="selection-table-scroll" tabindex="0" role="region" aria-label="작품 선택 표"><table class="selection-table" aria-describedby="selection-help"><caption class="sr-only">작품 목록 — 왼쪽 체크박스로 선택</caption><thead><tr><th scope="col">선택</th><th scope="col">artwork_id</th><th scope="col">artwork_title</th><th scope="col">artist</th><th scope="col">location</th><th scope="col">theme</th><th scope="col">description</th></tr></thead><tbody>${sorted.map(art => {
      const selected = chosen.some(item => item.id === art.id);
      const title = art.title_en || art.title;
      const description = art.description || '';
      return `<tr class="${selected ? 'is-selected' : ''}"><td class="selection-checkbox-cell"><input type="checkbox" id="choose-${escape(art.id)}" data-artwork-choice="${escape(art.id)}" aria-label="작품 ${escape(art.artwork_id)} ${escape(title)} 선택" ${selected ? 'checked' : ''}></td><th scope="row"><label for="choose-${escape(art.id)}">${escape(art.artwork_id)}</label></th><td>${escape(title)}</td><td>${escape(art.artist_name_en || art.artist_name)}</td><td>${escape(art.location)}</td><td>${escape(art.theme)}</td><td class="selection-description">${description.length > 80 ? `<details><summary>${escape(description.slice(0, 80))}… <span>더 보기</span></summary><p>${escape(description)}</p></details>` : escape(description)}</td></tr>`;
    }).join('')}</tbody></table></div>
    <div class="selection-route" aria-live="polite" aria-atomic="true"><span class="eyebrow">선택한 작품</span>${chosen.length ? `<ul aria-label="선택한 작품">${chosen.map(art => `<li><span class="route-artwork-id">${escape(art.artwork_id)}</span><span>${escape(art.title_en || art.title)}</span></li>`).join('')}</ul>` : '<p>선택한 작품이 없습니다.</p>'}</div>
  </section>`;
}
