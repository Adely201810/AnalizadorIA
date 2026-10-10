# CLAUDE.md — AnalizadorIA

## Reglas comunes (aplican siempre)

1. Trabaja UNA fase a la vez. No adelantes fases futuras.
2. Ejecuta las pruebas de verdad. Nunca describas de memoria lo que "debería" pasar.
3. Pega la salida EXACTA de cada prueba (sin resumir, sin redondear, sin inventar cifras).
4. Si algo falla, muestra el error exacto y la causa real ANTES de proponer o aplicar un arreglo. No marques nada como "listo" sin verificación.
5. Documenta cada fase por escrito en docs/FASE_XX.md: qué se implementó, qué decisiones se tomaron por cuenta propia y por qué, y los resultados reales.
6. No cambies la base de datos ni los datos. Las consultas contra los datos son solo de lectura.
7. Haz un commit de git por fase (o una rama por fase) para poder revertir.
8. Antes de descargar algo pesado (modelos, paquetes grandes), indica el tamaño aproximado y espera confirmación.
9. Si una decisión depende del negocio o de los datos, pregunta; no la supongas.

## Contexto

- Diagnóstico inicial: `DIAGNOSTICO.md`.
- Entorno y comandos reproducibles: `docs/ENTORNO.md`.
