# AGENTS.md

Guía de estándares y flujo de trabajo para agentes y desarrolladores.

> [!NOTE]
> Cada proyecto o repositorio contiene su propio `AGENTS.md` con las reglas específicas de dependencias, scripts y testing. Este documento define los **estándares globales de desarrollo, alcance por roles y capas técnicas, arquitectura limpia (DDD / Hexagonal / Puertos y Adaptadores), directrices de testing, control de versiones (Git) y trazabilidad con ClickUp**.

---

## 1. Alcance y Perfil de Desarrollo (Agnóstico y Configurable)

Este entorno y plantilla están diseñados como una **base agnóstica de frameworks, lenguajes y roles**, permitiendo adaptarse a cualquier stack tecnológico (Frontend, Backend, Fullstack, Mobile, CLI o Librerías) mediante configuración (`config.json`, variables de entorno en `.env` o flags de línea de comandos).

### 1.1 Configuración de Perfil
{{DEV_PROFILE_SUMMARY}}

- **Modo Agnóstico (`role: "agnostic"` - Por defecto):**
  - El agente inspecciona el repositorio activo (detectando archivos clave como `package.json`, `pyproject.toml`, `go.mod`, `pom.xml`, `Cargo.toml`, etc.) y aplica los cambios pertinentes al ámbito técnico de dicho repositorio.
  - **En proyectos Frontend:** Las subtareas `FE` constituyen el alcance directo de desarrollo; las subtareas `BE` proporcionan especificación de contratos, endpoints y modelos de datos.
  - **En proyectos Backend:** Las subtareas `BE` constituyen el alcance directo de desarrollo; las subtareas `FE` proporcionan contexto sobre flujos de usuario, pantallas y requerimientos del cliente.
  - **En proyectos Fullstack / Monorepos:** Ambas subtareas se desarrollan e integran de forma coordinada en sus respectivos módulos o paquetes.
- **Modos Específicos (`frontend`, `backend`, `fullstack`):**
  - Permiten restringir o enfocar explícitamente el alcance cuando se trabaja en repositorios dedicados.

### 1.2 Regla por Defecto para Ramas y Pull Requests (Ticket Principal)
- **Creación de ramas y PR por Historia Principal:** Por defecto, la rama de Git (`feature/PROJ-<####>-...`) y el Pull Request **deben crearse a nivel de la Historia / Ticket Principal**, **NO para cada subtarea individual**.
- **Integración continua de subtareas:** Todo el desarrollo correspondiente a las subtareas asociadas se realiza e integra de manera continua dentro de la misma rama del Ticket Principal.
- **Trazabilidad en Commits:** Los commits deben usar como identificador base el ID del Ticket Principal (`feat : PROJ-101 - ...`). De forma opcional y recomendada para mayor granularidad, se puede agregar el ID de la subtarea: `feat : PROJ-101_(T102) - <descripcion>`.
- **Documentación en el PR:** En la plantilla de Pull Request, bajo `## Tickets relacionados`, se debe incluir obligatoriamente el enlace al Ticket Principal de la historia y listar los enlaces de todas las subtareas asociadas implementadas.

### 1.3 Regla de Identificación mediante Prefijos (FE / BE vs. Historia Principal)
En caso de duda sobre cuál es el Ticket Principal frente a las subtareas al inspeccionar los archivos del directorio o tareas en ClickUp, utilizar la siguiente regla basada en prefijos de nomenclatura:

1. **Subtareas:** Siempre llevan el prefijo correspondiente a su ámbito técnico:
   - **`FE - <Nombre>`** (o `FE: ...`, `Frontend - ...`, `UI - ...`): Ámbito de **Frontend / UI / Cliente**.
   - **`BE - <Nombre>`** (o `BE: ...`, `Backend - ...`, `API - ...`, `DB - ...`): Ámbito de **Backend / Servidor / API / Base de Datos**.
2. **Historia Principal (Story):**
   - **NO lleva prefijo `FE` ni `BE`**. Su título describe el módulo o funcionalidad completa a nivel de negocio (ej. `PROJ - Integraciones - Conector de datos - ERP`).
   - Coincide con el nombre de la carpeta contenedora y con el archivo markdown principal que lista la tabla de subtareas.
   - **Es sobre este ticket donde se debe crear la rama Git y el PR por defecto.**
3. **Prerrequisitos:** Llevan el prefijo `PREVIUS TICKET NEEDED <Nombre>` y corresponden a tickets bloqueantes ("blocked by") previos.

---

## 2. Cumplimiento de Arquitectura (Arquitectura Limpia / Hexagonal / DDD)

Todo desarrollo debe estructurarse respetando la **Separación de Responsabilidades**, la **Inversión de Dependencias** y los principios de **Arquitectura Hexagonal (Puertos y Adaptadores)** combinados con **Domain-Driven Design (DDD)**:

### 2.1 Capas Arquitectónicas Fundamentales

1. **Dominio / Núcleo (Domain / Core):**
   - Entidades de negocio, Value Objects y reglas puras del dominio.
   - Definición de **Puertos** (interfaces o contratos abstractos de repositorios, clientes externos y servicios de dominio).
   - *Regla estricta:* Totalmente desacoplado de frameworks web, librerías de UI, clientes HTTP concretos, ORMs o mecanismos de I/O.
2. **Aplicación / Casos de Uso (Application / Use Cases):**
   - Casos de uso y orquestación de la lógica de aplicación.
   - Consume los puertos del dominio para ejecutar operaciones del negocio sin conocer los detalles de infraestructura.
3. **Infraestructura / Adaptadores Secundarios (Infrastructure / Driven Adapters):**
   - Implementaciones concretas de los puertos de dominio.
   - Servicios y clientes HTTP, repositorios con ORMs / consultas de base de datos, mensajería, adaptadores de terceros o almacenamiento local.
   - Mapeadores (*mappers* / *transformers*) que transforman DTOs externos a entidades del Dominio y viceversa.
4. **Presentación / Adaptadores Primarios (Presentation / Driving Adapters / UI / Controllers):**
   - **En Frontend:** Componentes de interfaz de usuario, vistas, páginas, rutas, guards y gestión reactiva de estado (consumiendo casos de uso o servicios de aplicación, nunca clientes HTTP directamente en componentes de presentación).
   - **En Backend:** Controladores HTTP/REST, resolvers GraphQL, endpoints gRPC, comandos CLI, serialización y validación de entrada.

> [!IMPORTANT]
> **Regla de Dependencias:** Las capas externas (Presentación e Infraestructura) conocen y dependen de las capas internas (Aplicación y Dominio). El Dominio jamás conoce ni depende de capas externas, frameworks o bases de datos.

---

## 3. Directrices de Pruebas y Testing (Unitarias, Integración y E2E)

### 3.1 Pruebas Unitarias y Organización de Tests
- **Enfoque en Lógica de Negocio:** La lógica central del Dominio y los Casos de Uso de Aplicación deben contar con pruebas unitarias rápidas, confiables y libres de mocks pesados de base de datos o red.
- **Organización de Tests:** Ubicar los archivos de prueba según los estándares convencionales del stack del proyecto (ej. `tests/`, `__tests__/`, carpetas espejo o junto al archivo fuente), manteniendo el núcleo de dominio limpio y enfocado exclusivamente en las reglas de negocio.
- **Adaptadores de Infraestructura:** Validar mediante pruebas de integración utilizando mocks, stubs o bases de datos en memoria para verificar la correcta comunicación con puertos externos.

### 3.2 Pruebas E2E y Funcionales: Simplicidad y Enfoque en lo Esencial
- **No sobrecomplicar con E2E:** Evitar el diseño de suites end-to-end excesivamente extensas o frágiles con combinaciones infinitas de casos borde que ralenticen los pipelines de CI o generen falsos positivos.
- **Versión simplificada y esencial:** Agregar **únicamente una versión simplificada de las pruebas funcionales / E2E estrictamente requeridas** para los cambios introducidos por el ticket.
- **Enfoque clave:** Validar el flujo crítico del usuario ("happy path" principal de la nueva funcionalidad, endpoint o pantalla clave). Las validaciones puntuales o casos extremos deben cubrirse a nivel unitario o de integración.

---

## 4. Flujo de Trabajo Recomendado

1. Leer el contexto mínimo necesario antes de editar.
2. Identificar el **Ticket Principal de ClickUp (`PROJ-<####>`)** y sus subtareas correspondientes.
3. **Verificar el contexto del repositorio y el ámbito de las subtareas:**
   - Si se trabaja en un repositorio Frontend: planificar e implementar subtareas `FE`; consultar subtareas `BE` como especificación de contrato.
   - Si se trabaja en un repositorio Backend: planificar e implementar subtareas `BE`; consultar subtareas `FE` como referencia de flujos y contratos UI.
   - Si se trabaja en un repositorio Fullstack / Monorepo: coordinar la implementación en ambas capas.
4. **Crear o verificar la rama de trabajo por defecto para la Historia Principal** (`feature/PROJ-<####>-<Descripción>`), evitando crear ramas aisladas por subtarea.
5. Ubicar el módulo, servicio o capa correcta dentro del proyecto respetando la **Arquitectura Limpia / Hexagonal** (Dominio, Aplicación, Infraestructura, Presentación).
6. Si el cambio toca funcionalidad crítica o modifica una cantidad de archivos superior a 3, generar un plan de trabajo y pedir confirmación del usuario antes de ejecutar cambios.
7. Realizar cambios consistentes con los patrones existentes en el repositorio.
8. **Validar con pruebas:**
   - Ejecutar pruebas unitarias locales pertinentes.
   - Si se requieren pruebas E2E/funcionales, mantenerlas **simplificadas y limitadas al flujo esencial** introducido por el cambio.
   - Validar con linter, formateador y herramientas de tipado/compilación del proyecto.
9. Realizar commits referenciando el Ticket Principal (`feat : PROJ-101 - ...` o `feat : PROJ-101_(T102) - ...`).
10. **Abrir el Pull Request para la Historia Principal**, utilizando obligatoriamente la plantilla de PR del repositorio, titulándolo con el ID principal y listando las subtareas implementadas en `## Tickets relacionados`.
11. Documentar brevemente riesgos, supuestos o validaciones no ejecutadas.

---

## 5. Git: Ramas, Commits y Pull Requests (Estándares de Trabajo)

Todos los agentes y desarrolladores deben apegarse estrictamente a los estándares de control de versiones y trazabilidad ClickUp-GitHub definidos para el flujo de trabajo del proyecto.

### 5.1 Nomenclatura de creación de ramas

#### Ramas principales
Las ramas principales no deben renombrarse ni eliminarse:
- **Producción:** `master` o `main`
- **Desarrollo:** `dev` o `develop`
- **Pruebas Testing:** `test` o `qa`
- **Pruebas UAT:** `demo` o `staging`
- **Pre-producción:** `preprod`

#### Ramas secundarias de trabajo
Toda rama secundaria debe incluir obligatoriamente el prefijo de tipo y el identificador de ticket personalizado de ClickUp (`PROJ-<####>`) para garantizar la vinculación automática con ClickUp:

| Tipo de Rama | Nomenclatura | Rama Base | Uso y Tiempo de Vida |
|---|---|---|---|
| **Release Candidate (RC)** | `RC/PROJ-<####>-<Descripción>` | `dev` | Funcionalidades complejas o con estimación > 1 semana. Concentra el avance antes de integrarse al flujo normal de `dev`. Creada por Versionador o Líder Técnico. |
| **Feature** | `feature/PROJ-<####>-<Descripción>` | `dev` (flujo normal) o rama `RC/` | Desarrollo de nuevas funcionalidades (< 1 semana en flujo normal, o subtareas bajo una rama RC). Creada por Desarrollador. Se elimina tras integrarse a su rama destino. |
| **Bugfix** | `bugfix/PROJ-<####>-<Descripción>` | `test` o `demo` (según dónde se detectó) | Corrección de bugs detectados durante pruebas de testing o UAT del Release Plan. Creada por Desarrollador. Se elimina tras integrarse a `test`/`demo`. |
| **Coldfix** | `coldfix/PROJ-<####>-<Descripción>` | `dev` (flujo normal) o rama `RC/` | Corrección de incidencias productivas de impacto bajo que se gestionan dentro del Release Plan. Creada por Desarrollador. Se elimina tras integrarse. |
| **Hotfix** | `hotfix/PROJ-<####>-<Descripción>` | `master` o `main` | Corrección de incidencias productivas críticas o de alto impacto fuera del Release Plan. Creada por Desarrollador. Se elimina tras integrarse a producción. |

**Reglas clave para ramas:**
- Formato: `<tipo>/PROJ-<####>-<Descripción o Título en kebab-case>`
- **Por defecto, usar el identificador de la Historia Principal (`PROJ-<####>`), no el de las subtareas.**
- Ejemplos:
  - `RC/PROJ-101-conector-de-datos-erp`
  - `feature/PROJ-101-conector-de-datos-erp`
  - `bugfix/PROJ-102-nuevos-filtros-de-busqueda`
  - `coldfix/PROJ-103-guardado-de-documentos`
  - `hotfix/PROJ-104-correccion-critica-autenticacion`

---

### 5.2 Nomenclatura para commits

Cada commit debe estructurarse con la sintaxis requerida para la vinculación automática con ClickUp y el histórico claro de cambios:

$$\text{Formato: } \texttt{<tipo> : PROJ-<####> - <Descripción>}$$
$$\text{Opcional con subtarea: } \texttt{<tipo> : PROJ-<####>\_(T<subtarea>) - <Descripción>}$$

| Prefijo / Tipo | Finalidad | Ejemplo |
|---|---|---|
| `feat` | Nuevas funcionalidades | `feat : PROJ-101 - conector de datos erp` o `feat : PROJ-101_(T102) - componente pestana datos` |
| `bugfix` | Corrección de bugs en pruebas | `bugfix : PROJ-102_(T103) - Corrección al guardar un nuevo producto` |
| `coldfix` | Corrección de incidencias de bajo impacto (Release Plan) | `coldfix : PROJ-103 - Corrección en cálculo de montos` |
| `hotfix` | Incidencias productivas críticas o alto impacto | `hotfix : PROJ-104 - Corrección en autenticación de usuarios` |
| `format` | Formateo de código, limpieza, linters y mantenimiento | `format : PROJ-105 - formateo y limpieza de código` |
| `conf` | Cambios de configuración de proyecto, build, scripts, CI/CD | `conf : PROJ-106 - nuevos recursos de despliegue para el proyecto` |

**Consideraciones:**
- Respetar siempre el espacio antes y después de los dos puntos: `<tipo> : PROJ-...`.
- Respetar el prefijo `PROJ-<####>` exacto del ticket de ClickUp para permitir la trazabilidad automática.
- No crear commits con descripciones vagas o genéricas (ej. "fix", "wip", "update").

---

### 5.3 Creación de Pull Requests y Plantilla Obligatoria

Al crear un Pull Request (PR) en GitHub:

1. **Título del PR:**
   - **Por defecto, abrir el PR para la Historia Principal:**
     ```text
     <Tipo> : PROJ-<####> - <Descripción de la Historia>
     ```
     Donde `<Tipo>` corresponde a: `Feature`, `Bugfix`, `Coldfix`, `Hotfix`, `Conf`, `Liberación a producción`, etc.  
     *Ejemplo:* `Feature : PROJ-101 - Conector de datos ERP`
   - Para liberación de Release Candidate:
     ```text
     Liberación Release Candidate : PROJ-<####>
     ```

2. **Uso obligatorio de la plantilla de PR del repositorio:**
   Todo PR debe ser documentado llenando completamente las secciones del template del repositorio:
   - **`## Descripción`**: Breve resumen de los cambios y el contexto funcional o técnico de la historia y subtareas abordadas.
   - **`## Tickets relacionados`**:
     - Enlace obligatorio al **Ticket Principal de ClickUp** (`https://app.clickup.com/t/...`).
     - Lista de enlaces a las **Subtareas implementadas** (ej. `Subtarea: https://app.clickup.com/t/...`).
   - **`## Cambios realizados`**: Detallar qué componentes, servicios, endpoints o adaptadores se agregaron o modificaron.
   - **`## Checklist`**: Marcar las casillas correspondientes:
     - [ ] Código probado localmente
     - [ ] Tests unitarios agregados/actualizados
     - [ ] Tests E2E / integración esenciales agregados (si aplica)
     - [ ] Documentación actualizada
     - [ ] Sin breaking changes
   - **`## Cómo probarlo`**: Pasos secuenciales y reproducibles para validar el PR.
   - **`## Screenshots / Evidencias (opcional)`**: Adjuntar capturas, logs o videos si aplica.
   - **`## Notas adicionales`**: Registrar riesgos, dependencias o decisiones de diseño tomadas.

3. **Trazabilidad y vinculación con ClickUp:**
   - Asegurarse de que el PR esté asociado a la tarea de ClickUp (vía título, rama o vinculación manual en ClickUp).
   - Documentar la URL del PR generado en el ticket de ClickUp y notificar al revisor técnico asignado.
