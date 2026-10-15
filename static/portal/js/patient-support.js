(() => {
    const section = document.querySelector('.patient-support');
    const phrase = document.getElementById('patient-support-phrase');
    const button = document.getElementById('patient-support-next');
    if (!section || !phrase || !button) return;
    const phrases = [
        'No tienes que resolver todo hoy. Puedes ir un paso a la vez.',
        'Lo que sientes merece ser escuchado, incluso cuando cuesta explicarlo.',
        'Puedes darte una pausa sin tener que ganártela.',
        'Pedir compañía también es una forma de cuidarte.',
        'Un día difícil no define quién eres ni todo tu camino.',
        'Puedes avanzar a tu ritmo. No necesitas compararte con nadie.',
        'No hace falta tener todas las respuestas para empezar a hablar.',
        'Tus límites importan. Puedes expresar lo que necesitas.',
        'También mereces la paciencia que ofreces a otras personas.',
        'Hoy puedes elegir algo pequeño que te haga sentir más a gusto.',
        'Está bien sentir varias cosas a la vez. No tienes que ordenarlas de inmediato.',
        'Cada conversación puede ser un espacio para conocerte un poco más.',
    ];
    const day = Date.parse(section.dataset.day + 'T00:00:00Z');
    let index = Number.isFinite(day) ? Math.floor(day / 86400000) % phrases.length : 0;
    phrase.textContent = phrases[index];
    button.hidden = false;
    button.addEventListener('click', () => {
        index = (index + 1) % phrases.length;
        phrase.textContent = phrases[index];
    });
})();
