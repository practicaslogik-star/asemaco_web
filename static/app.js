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

