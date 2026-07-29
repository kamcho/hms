/**
 * ICD-11 diagnosis search-select for clinical forms.
 * Search: local HMS DB. On select: cross-check with DHA terminology API.
 */
function initIcd11DiagnosisPicker(root) {
    if (!root || root.dataset.icdInitialized === '1') return;

    const searchUrl = root.dataset.searchUrl;
    const validateUrl = root.dataset.validateUrl || '';
    const searchInput = root.querySelector('.icd-diagnosis-search');
    const resultsDiv = root.querySelector('.icd-diagnosis-results');
    const selectedBox = root.querySelector('.icd-diagnosis-selected');
    const selectedLabel = root.querySelector('.icd-diagnosis-selected-label');
    const selectedMeta = root.querySelector('.icd-diagnosis-selected-meta');
    const clearBtn = root.querySelector('.icd-diagnosis-clear');
    const valueField = root.querySelector('.icd-diagnosis-value');
    const statusEl = root.querySelector('.icd-diagnosis-validate-status');
    const checkingBox = root.querySelector('.icd-diagnosis-checking');
    const checkingLabel = root.querySelector('.icd-diagnosis-checking-label');

    if (!searchInput || !resultsDiv || !valueField || !searchUrl) return;

    root.dataset.icdInitialized = '1';
    let debounceTimer = null;
    let activeController = null;
    let latestRequestId = 0;
    let lastQuery = '';
    let validateController = null;

    function formatDiagnosis(item) {
        const title = (item && item.title) ? String(item.title).trim() : '';
        const code = (item && item.code) ? String(item.code).trim() : '';
        if (code && title) return code + ' — ' + title;
        return title || code || '';
    }

    function setValidating(isValidating, item) {
        root.classList.toggle('is-validating', !!isValidating);
        searchInput.disabled = !!isValidating;
        if (clearBtn) clearBtn.disabled = !!isValidating;
        if (!checkingBox) return;
        if (isValidating) {
            if (checkingLabel) {
                checkingLabel.textContent = formatDiagnosis(item) || 'Validating terminology…';
            }
            checkingBox.classList.remove('hidden');
            selectedBox.classList.add('hidden');
            resultsDiv.classList.add('hidden');
        } else {
            checkingBox.classList.add('hidden');
        }
    }

    function setValidateStatus(message, tone) {
        if (!statusEl) return;
        if (!message) {
            statusEl.classList.add('hidden');
            statusEl.textContent = '';
            statusEl.className = 'icd-diagnosis-validate-status text-[11px] font-semibold mt-2 ml-1 hidden';
            return;
        }
        const tones = {
            ok: 'text-emerald-600',
            warn: 'text-amber-600',
            error: 'text-rose-600',
            loading: 'text-indigo-600',
        };
        statusEl.className = 'icd-diagnosis-validate-status text-[11px] font-semibold mt-2 ml-1 ' + (tones[tone] || tones.loading);
        if (tone === 'loading') {
            statusEl.innerHTML = '<span class="inline-flex items-center gap-1.5"><span class="icd-diagnosis-spinner" style="width:12px;height:12px;border-width:2px;"></span>' + message + '</span>';
        } else {
            statusEl.textContent = message;
        }
        statusEl.classList.remove('hidden');
    }

    function showSelected(item, metaExtra) {
        const text = formatDiagnosis(item);
        if (!text) return;
        valueField.value = text;
        selectedLabel.textContent = text;
        selectedMeta.textContent = [
            item.code ? 'ICD-11 ' + item.code : '',
            item.id ? 'Entity ' + item.id : '',
            metaExtra || '',
        ].filter(Boolean).join(' · ');
        selectedBox.classList.remove('hidden');
        searchInput.value = titleOrQuery(item);
        resultsDiv.classList.add('hidden');
        resultsDiv.innerHTML = '';
    }

    function titleOrQuery(item) {
        return (item && item.title) ? item.title : (item && item.code) ? item.code : '';
    }

    function clearSelection() {
        if (root.classList.contains('is-validating')) return;
        valueField.value = '';
        searchInput.value = '';
        selectedBox.classList.add('hidden');
        selectedLabel.textContent = '';
        selectedMeta.textContent = '';
        resultsDiv.classList.add('hidden');
        resultsDiv.innerHTML = '';
        setValidating(false);
        setValidateStatus('', '');
        searchInput.focus();
    }

    async function validateWithDha(item) {
        if (!validateUrl || !item || !item.code) {
            showSelected(item, 'Local only');
            setValidateStatus('Selected from local ICD-11 (DHA validate URL not configured).', 'warn');
            return;
        }

        if (validateController) validateController.abort();
        validateController = new AbortController();
        setValidating(true, item);
        setValidateStatus('Checking with DHA terminology…', 'loading');
        valueField.value = '';

        try {
            const params = new URLSearchParams({
                code: item.code,
                title: item.title || '',
            });
            const res = await fetch(validateUrl + '?' + params.toString(), {
                headers: { Accept: 'application/json' },
                signal: validateController.signal,
            });
            const data = await res.json();
            setValidating(false);

            if (data.success) {
                const display = data.display || formatDiagnosis(item);
                const parts = display.split(' — ');
                const validatedItem = {
                    code: data.code || item.code,
                    title: parts.length > 1 ? parts.slice(1).join(' — ') : (item.title || ''),
                    id: item.id,
                };
                showSelected(validatedItem, data.status === 'validated' ? 'DHA verified' : 'Local OK');
                setValidateStatus(data.message || 'Validated.', data.status === 'validated' ? 'ok' : 'warn');
                return;
            }

            if (data.status === 'title_changed' && data.suggested_display) {
                const parts = String(data.suggested_display).split(' — ');
                showSelected({
                    code: data.code || item.code,
                    title: parts.length > 1 ? parts.slice(1).join(' — ') : (data.dha && data.dha.title) || item.title,
                    id: item.id,
                }, 'DHA title applied');
                setValidateStatus(data.message || 'Title updated from DHA.', 'warn');
                return;
            }

            clearSelection();
            setValidateStatus(data.message || data.error || 'DHA rejected this ICD-11 code.', 'error');
        } catch (err) {
            if (err && err.name === 'AbortError') return;
            setValidating(false);
            showSelected(item, 'Local (DHA check failed)');
            setValidateStatus('Could not reach DHA validate endpoint. Local selection kept.', 'warn');
        }
    }

    function renderResults(items) {
        resultsDiv.innerHTML = '';
        if (!items || !items.length) {
            resultsDiv.innerHTML = '<div class="p-4 text-xs font-bold text-slate-400 text-center">No ICD-11 matches in local DB.</div>';
            resultsDiv.classList.remove('hidden');
            return;
        }

        items.slice(0, 25).forEach(function (item) {
            const row = document.createElement('button');
            row.type = 'button';
            row.className = 'w-full text-left p-3 hover:bg-slate-50 border-b border-slate-50 last:border-0';
            const code = item.code ? '<span class="text-[10px] font-black uppercase tracking-wider text-indigo-600 bg-indigo-50 px-1.5 py-0.5 rounded mr-2">' + item.code + '</span>' : '';
            row.innerHTML = '<div class="font-bold text-slate-800 text-sm">' + code + (item.title || 'Untitled') + '</div>'
                + (item.chapter ? '<div class="text-[10px] font-semibold text-slate-400 mt-1">Chapter ' + item.chapter + '</div>' : '');
            row.addEventListener('click', function () {
                if (root.classList.contains('is-validating')) return;
                validateWithDha(item);
            });
            resultsDiv.appendChild(row);
        });
        resultsDiv.classList.remove('hidden');
    }

    function renderError(message) {
        resultsDiv.innerHTML = '<div class="p-4 text-xs font-bold text-rose-500 text-center">' + message + '</div>';
        resultsDiv.classList.remove('hidden');
    }

    async function runSearch(query) {
        if (root.classList.contains('is-validating')) return;
        const q = (query || '').trim();
        if (q.length < 2) {
            resultsDiv.classList.add('hidden');
            resultsDiv.innerHTML = '';
            lastQuery = '';
            return;
        }
        if (q === lastQuery && resultsDiv.children.length) {
            resultsDiv.classList.remove('hidden');
            return;
        }

        if (activeController) activeController.abort();
        activeController = new AbortController();
        const requestId = ++latestRequestId;

        resultsDiv.innerHTML = '<div class="p-4 text-xs font-semibold text-slate-500 text-center inline-flex items-center justify-center gap-2 w-full"><span class="icd-diagnosis-spinner" style="width:14px;height:14px;border-width:2px;"></span> Searching local ICD-11…</div>';
        resultsDiv.classList.remove('hidden');

        try {
            const url = searchUrl + '?q=' + encodeURIComponent(q);
            const res = await fetch(url, {
                headers: { Accept: 'application/json' },
                signal: activeController.signal,
            });
            const data = await res.json();
            if (requestId !== latestRequestId) return;
            lastQuery = q;
            if (!res.ok || !data.success) {
                renderError(data.error || 'ICD-11 search failed.');
                return;
            }
            renderResults(data.results || []);
        } catch (err) {
            if (err && err.name === 'AbortError') return;
            if (requestId !== latestRequestId) return;
            renderError('Could not reach ICD-11 search.');
        }
    }

    searchInput.addEventListener('input', function () {
        clearTimeout(debounceTimer);
        debounceTimer = setTimeout(function () {
            runSearch(searchInput.value);
        }, 450);
    });

    searchInput.addEventListener('focus', function () {
        if (root.classList.contains('is-validating')) return;
        const q = searchInput.value.trim();
        if (q.length >= 2 && q !== lastQuery) {
            runSearch(q);
        } else if (q.length >= 2 && resultsDiv.children.length) {
            resultsDiv.classList.remove('hidden');
        }
    });

    document.addEventListener('click', function (e) {
        if (!root.contains(e.target)) {
            resultsDiv.classList.add('hidden');
        }
    });

    if (clearBtn) {
        clearBtn.addEventListener('click', clearSelection);
    }

    const form = root.closest('form');
    if (form) {
        form.addEventListener('submit', function (e) {
            if (root.classList.contains('is-validating')) {
                e.preventDefault();
                setValidateStatus('Still checking with DHA terminology — please wait.', 'loading');
                return;
            }
            if (!valueField.value.trim()) {
                e.preventDefault();
                setValidateStatus('Select an ICD-11 diagnosis from search results (DHA-verified).', 'error');
                searchInput.focus();
            }
        });
    }

    if (valueField.value && valueField.value.trim()) {
        selectedLabel.textContent = valueField.value.trim();
        selectedMeta.textContent = 'Existing diagnosis';
        selectedBox.classList.remove('hidden');
        searchInput.value = valueField.value.trim();
        setValidateStatus('Existing value — re-select to re-validate with DHA.', 'warn');
    }
}

function initAllIcd11DiagnosisPickers() {
    document.querySelectorAll('.icd-diagnosis-picker').forEach(initIcd11DiagnosisPicker);
}

document.addEventListener('DOMContentLoaded', initAllIcd11DiagnosisPickers);
