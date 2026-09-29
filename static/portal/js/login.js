(() => {
    const form = document.getElementById('login-form');
    if (!form) return;
    const email = document.getElementById('login-email');
    const password = document.getElementById('login-password');
    const submit = document.getElementById('login-submit');
    const status = document.getElementById('login-status');
    const toggle = document.getElementById('toggle-password');
    const caps = document.getElementById('caps-warning');
    const touched = new Set();
    // Native required/email validation remains available without JavaScript.
    form.noValidate = true;
    toggle.hidden = false;

    function validate(field) {
        let error = '';
        if (field === email) {
            email.value = email.value.trim();
            if (!email.value) error = 'Escribe el correo electrónico con el que creaste tu cuenta.';
            else if (email.validity.typeMismatch || !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email.value)) {
                error = 'El correo no tiene un formato válido. Escríbelo como nombre@ejemplo.com.';
            }
        } else if (!password.value) {
            error = 'Escribe tu contraseña para continuar. Si no la recuerdas, selecciona «¿Olvidaste tu contraseña?».';
        }
        document.getElementById(field === email ? 'email-error' : 'password-error').textContent = error;
        field.setAttribute('aria-invalid', String(Boolean(error)));
        return !error;
    }

    for (const field of [email, password]) {
        if (field.getAttribute('aria-invalid') === 'true') touched.add(field);
        field.addEventListener('blur', () => { touched.add(field); validate(field); });
        field.addEventListener('input', () => {
            if (touched.has(field)) validate(field);
            const serverError = document.getElementById('login-error');
            if (serverError) serverError.hidden = true;
            status.textContent = '';
        });
    }
    form.addEventListener('submit', event => {
        if (submit.disabled) { event.preventDefault(); return; }
        const fields = [email, password];
        const invalid = fields.filter(field => { touched.add(field); return !validate(field); });
        if (invalid.length) {
            event.preventDefault();
            status.textContent = 'Revisa los campos marcados antes de continuar.';
            invalid[0].focus();
            return;
        }
        submit.disabled = true;
        submit.textContent = 'Verificando…';
        form.setAttribute('aria-busy', 'true');
        status.textContent = 'Estamos comprobando tus datos de acceso.';
    });
    toggle.addEventListener('click', () => {
        const show = password.type === 'password';
        password.type = show ? 'text' : 'password';
        toggle.textContent = show ? 'Ocultar' : 'Mostrar';
        toggle.setAttribute('aria-pressed', String(show));
    });
    for (const name of ['keydown', 'keyup']) {
        password.addEventListener(name, event => { caps.hidden = !event.getModifierState('CapsLock'); });
    }
    password.addEventListener('blur', () => { caps.hidden = true; });
    window.addEventListener('pageshow', () => {
        submit.disabled = false;
        submit.textContent = 'Iniciar sesión';
        form.removeAttribute('aria-busy');
        status.textContent = '';
    });
    const firstError = form.querySelector('[aria-invalid="true"]') || document.getElementById('login-error');
    firstError?.focus();
})();
