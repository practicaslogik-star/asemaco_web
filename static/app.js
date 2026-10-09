'use strict';
const catalogNode = document.getElementById('catalog-data');
if (catalogNode) { const catalogs = JSON.parse(catalogNode.dataset.catalog); document.querySelectorAll('[data-fill]').forEach(select => select.addEventListener('change', () => { const item = catalogs[select.dataset.kind].find(e => String(e.id) === select.value); if (!item) return; const prefix = select.dataset.fill; Object.entries(item).forEach(([key, value]) => { let name = prefix + '_' + key; if (prefix === 'vehicle') name = key === 'name' ? 'vehicle' : key === 'trailer' ? 'trailer' : ''; const input = document.querySelector('[name="' + name + '"]'); if (input) input.value = value; }); })); }
document.querySelectorAll('[data-confirm]').forEach(button => button.addEventListener('click', e => { if (!window.confirm(button.dataset.confirm)) e.preventDefault(); }));
document.querySelectorAll('[data-copy]').forEach(button => button.addEventListener('click', async () => { const field = document.getElementById(button.dataset.copy); try { await navigator.clipboard.writeText(field.value); button.textContent = 'Enlace copiado'; } catch { field.focus(); field.select(); button.textContent = 'Seleccionado: copia el enlace'; } }));
document.getElementById('doc-search')?.addEventListener('input', e => { const q = e.target.value.toLocaleLowerCase('es'); document.querySelectorAll('#docs-table tbody tr').forEach(r => r.hidden = !r.textContent.toLocaleLowerCase('es').includes(q)); });
document.getElementById('document-form')?.addEventListener('submit', e => {
    const saveCheckbox = document.querySelector('[name="save_all_data"]');
    if (saveCheckbox && !saveCheckbox.checked && localStorage.getItem('hideSaveWarning') !== 'true' && window.userPrefersNoWarning !== true) {
        e.preventDefault();
        document.getElementById('save-warning-modal')?.showModal();
        return;
    }
    const button = document.getElementById('generate');
    if (button) { button.disabled = true; button.textContent = 'Generando documento…'; }
});

document.getElementById('modal-cancel')?.addEventListener('click', () => {
    document.getElementById('save-warning-modal')?.close();
});

document.getElementById('modal-proceed')?.addEventListener('click', () => {
    if (document.getElementById('dont-show-again')?.checked) {
        localStorage.setItem('hideSaveWarning', 'true');
        const hiddenInput = document.getElementById('hidden_hide_save_warning');
        if (hiddenInput) hiddenInput.value = '1';
    }
    document.getElementById('save-warning-modal')?.close();
    const button = document.getElementById('generate');
    if (button) { button.disabled = true; button.textContent = 'Generando documento…'; }
    document.getElementById('document-form')?.submit();
});

// --- Lógica para mostrar y ocultar contraseñas ---
document.querySelectorAll('.password-toggle').forEach(boton => {
    boton.addEventListener('click', () => {
        // 1. Buscamos el input y el icono que están junto a este botón
        const contenedor = boton.closest('.password-wrapper');
        const input = contenedor.querySelector('input');
        const icono = boton.querySelector('i');

        // 2. Si el tipo es 'password' (puntos), lo pasamos a 'text' (visible)
        if (input.type === 'password') {
            input.type = 'text';
            // Cambiamos el icono por el del ojo tachado
            if (icono) {
                icono.classList.remove('bx-show');
                icono.classList.add('bx-hide');
            }
        } else {
            // Si ya era visible, lo volvems a ocultar
            input.type = 'password';
            // Volvemos a poner el ojo normal
            if (icono) {
                icono.classList.remove('bx-hide');
                icono.classList.add('bx-show');
            }
        }
    });
});

// modales de editar y borrar

const deleteModal = document.getElementById('delete-modal');
const editModal = document.getElementById('edit-modal');

// abirir modal eliminar
document.querySelectorAll('.btn-delete').forEach(btn => {
    btn.addEventListener('click', () => {
        const id = btn.dataset.id;
        const name = btn.dataset.name;

        const idInput = document.getElementById('delete-record-id');
        const nameEl = document.getElementById('delete-record-name');

        if (idInput) idInput.value = id;
        if (nameEl) nameEl.textContent = `"${name}"`;

        deleteModal?.showModal();
    });
});

// Cerrar modal de eliminación
document.getElementById('cancel-delete-btn')?.addEventListener('click', () => {
    deleteModal?.close();
});

//abrir modal editar
document.querySelectorAll('.btn-edit').forEach(btn => {
    btn.addEventListener('click', () => {
        const id = btn.dataset.id;
        let info = {};
        try {
            info = JSON.parse(btn.dataset.info || '{}');
        } catch (e) {
            console.error('Error parseando datos del registro:', e);
        }

        // Asignar el ID al campo oculto
        const idInput = document.getElementById('edit-record-id');
        if (idInput) idInput.value = id;

        // Rellenar cada input según los datos del registro (nombre, nif, dirección, etc.)
        Object.entries(info).forEach(([key, val]) => {
            const input = document.getElementById(`edit-field-${key}`);
            if (input) input.value = val || '';
        });

        editModal?.showModal();
    });
});

// Cerrar modal de modificación
document.getElementById('cancel-edit-btn')?.addEventListener('click', () => {
    editModal?.close();
});

// Cerrar modales si el usuario hace clic fuera de la ventana (en el fondo oscuro)
[deleteModal, editModal].forEach(modal => {
    modal?.addEventListener('click', (e) => {
        if (e.target === modal) modal.close();
    });
});

// --- Buscador y Paginación Reutilizable (Datos Habituales y Admin) ---
function setupGridPaginationAndSearch({
    gridSelector,
    cardSelector,
    searchId,
    clearBtnId,
    resetBtnId,
    noResultsId,
    paginationContainerId,
    paginationInfoId,
    paginationControlsId,
    pageSize = 8,
    itemLabel = 'registro'
}) {
    const grid = document.querySelector(gridSelector);
    if (!grid) return;

    const searchInput = document.getElementById(searchId);
    const clearBtn = document.getElementById(clearBtnId);
    const resetBtn = document.getElementById(resetBtnId);
    const noResults = document.getElementById(noResultsId);
    const paginationContainer = document.getElementById(paginationContainerId);
    const paginationInfo = document.getElementById(paginationInfoId);
    const paginationControls = document.getElementById(paginationControlsId);

    const allCards = Array.from(grid.querySelectorAll(cardSelector));
    let currentPage = 1;
    let filteredCards = [...allCards];

    function normalizeText(str) {
        return (str || '')
            .toLowerCase()
            .normalize('NFD')
            .replace(/[\u0300-\u036f]/g, '');
    }

    function render() {
        const totalItems = filteredCards.length;
        const totalPages = Math.ceil(totalItems / pageSize) || 1;

        if (currentPage > totalPages) currentPage = totalPages;
        if (currentPage < 1) currentPage = 1;

        allCards.forEach(card => {
            card.style.display = 'none';
        });

        const start = (currentPage - 1) * pageSize;
        const end = start + pageSize;
        const pageCards = filteredCards.slice(start, end);
        pageCards.forEach(card => {
            card.style.display = 'flex';
        });

        if (noResults) {
            const query = searchInput ? searchInput.value.trim() : '';
            if (totalItems === 0 && allCards.length > 0) {
                noResults.style.display = 'block';
                const strong = noResults.querySelector('strong');
                if (strong) strong.textContent = query;
            } else {
                noResults.style.display = 'none';
            }
        }

        if (paginationContainer) {
            if (allCards.length === 0 || totalItems === 0) {
                paginationContainer.style.display = 'none';
                return;
            }

            paginationContainer.style.display = 'flex';

            if (paginationInfo) {
                const first = start + 1;
                const last = Math.min(end, totalItems);
                paginationInfo.textContent = `Mostrando ${first}-${last} de ${totalItems} ${itemLabel}${totalItems === 1 ? '' : 's'}`;
            }

            if (paginationControls) {
                if (totalPages <= 1) {
                    paginationControls.innerHTML = '';
                    return;
                }

                let html = '';
                const btnPrefix = gridSelector.replace(/[^a-zA-Z0-9]/g, '');
                html += `<button type="button" class="pagination-btn" id="${btnPrefix}-prev" ${currentPage === 1 ? 'disabled' : ''} title="Página anterior">
                    <i class='bx bx-chevron-left'></i>
                </button>`;

                for (let i = 1; i <= totalPages; i++) {
                    if (totalPages <= 7 || i === 1 || i === totalPages || (i >= currentPage - 1 && i <= currentPage + 1)) {
                        html += `<button type="button" class="pagination-btn ${i === currentPage ? 'active' : ''}" data-page="${i}">${i}</button>`;
                    } else if (i === currentPage - 2 || i === currentPage + 2) {
                        html += `<span style="padding: 0 4px; color: var(--muted); font-size: 0.85rem;">…</span>`;
                    }
                }

                html += `<button type="button" class="pagination-btn" id="${btnPrefix}-next" ${currentPage === totalPages ? 'disabled' : ''} title="Página siguiente">
                    <i class='bx bx-chevron-right'></i>
                </button>`;

                paginationControls.innerHTML = html;

                paginationControls.querySelectorAll('[data-page]').forEach(btn => {
                    btn.addEventListener('click', () => {
                        currentPage = parseInt(btn.dataset.page, 10);
                        render();
                        grid.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
                    });
                });

                paginationControls.querySelector(`#${btnPrefix}-prev`)?.addEventListener('click', () => {
                    if (currentPage > 1) {
                        currentPage--;
                        render();
                        grid.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
                    }
                });

                paginationControls.querySelector(`#${btnPrefix}-next`)?.addEventListener('click', () => {
                    if (currentPage < totalPages) {
                        currentPage++;
                        render();
                        grid.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
                    }
                });
            }
        }
    }

    function handleSearch() {
        const query = normalizeText(searchInput ? searchInput.value.trim() : '');
        if (clearBtn) {
            clearBtn.style.display = query ? 'flex' : 'none';
        }

        if (!query) {
            filteredCards = [...allCards];
        } else {
            filteredCards = allCards.filter(card => {
                const text = normalizeText(card.textContent);
                return text.includes(query);
            });
        }
        currentPage = 1;
        render();
    }

    searchInput?.addEventListener('input', handleSearch);

    clearBtn?.addEventListener('click', () => {
        if (searchInput) {
            searchInput.value = '';
            searchInput.focus();
        }
        handleSearch();
    });

    resetBtn?.addEventListener('click', () => {
        if (searchInput) {
            searchInput.value = '';
            searchInput.focus();
        }
        handleSearch();
    });

    render();
}

// Inicializar en Datos Habituales
setupGridPaginationAndSearch({
    gridSelector: '.saved-records-grid',
    cardSelector: '.saved-card',
    searchId: 'record-search',
    clearBtnId: 'clear-search-btn',
    resetBtnId: 'reset-search-btn',
    noResultsId: 'no-search-results',
    paginationContainerId: 'pagination-container',
    paginationInfoId: 'pagination-info',
    paginationControlsId: 'pagination-controls',
    pageSize: 8,
    itemLabel: 'registro'
});

// Inicializar en Administración (Cuentas de socios)
setupGridPaginationAndSearch({
    gridSelector: '.members-grid',
    cardSelector: '.member-card',
    searchId: 'member-search',
    clearBtnId: 'clear-member-search-btn',
    resetBtnId: 'reset-member-search-btn',
    noResultsId: 'no-member-search-results',
    paginationContainerId: 'member-pagination-container',
    paginationInfoId: 'member-pagination-info',
    paginationControlsId: 'member-pagination-controls',
    pageSize: 8,
    itemLabel: 'socio'
});

// Cerrar desplegable de restablecer contraseña al hacer clic fuera
document.addEventListener('click', (e) => {
    document.querySelectorAll('.member-reset-dropdown[open]').forEach(details => {
        if (!details.contains(e.target)) {
            details.removeAttribute('open');
        }
    });
});

