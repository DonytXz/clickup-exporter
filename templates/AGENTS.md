# AGENTS.md

Guía de estándares y flujo de trabajo para agentes y desarrolladores.

> [!NOTE]
> Cada proyecto o repositorio contiene su propio `AGENTS.md` con las reglas específicas de dependencias, scripts y testing. Este documento define los **estándares globales de desarrollo, alcance frontend/backend, arquitectura DDD-hexagonal, directrices de testing, control de versiones (Git) y trazabilidad con ClickUp**.

---

## 1. Alcance y Rol de Desarrollo (Frontend First)

Este entorno de trabajo está configurado con un rol principal de **Frontend Developer (Angular / TypeScript / UI)**.

Al procesar historias de ClickUp y sus subtareas correspondientes:

- **Subtareas Frontend (`FE - ...` / Frontend):**
  - Constituyen el **alcance directo de implementación y trabajo**.
  - En estas subtareas se implementan los componentes, servicios, vistas, rutas, estilos, validaciones de interfaz y pruebas unitarias.
- **Subtareas Backend (`BE - ...` / Backend):**
  - Tienen carácter **estrictamente informativo y de contexto técnico**.
  - Se utilizan como referencia para conocer los contratos de datos, especificaciones de endpoints REST, DTOs (Data Transfer Objects), queries de base de datos o códigos de respuesta HTTP.
  - **NO se debe modificar ni generar código de backend**, **EXCEPTO SI:**
    1. El usuario lo instruye de forma explícita en la conversación (ej. *"implementa también el endpoint de BE"*, *"corrige el servicio en el backend"*), O
    2. El workspace o repositorio activo es explícitamente un proyecto de Backend (y no el proyecto de Angular o Frontend).

### 1.1 Regla por Defecto para Ramas y Pull Requests (Ticket Principal)
- **Creación de ramas y PR por Historia Principal:** Por defecto, la rama de Git (`feature/PROJ-<####>-...`) y el Pull Request **deben crearse a nivel de la Historia / Ticket Principal**, **NO para cada subtarea individual**.
- **Integración de subtareas:** Todo el desarrollo correspondiente a las subtareas de Frontend (`FE - ...`) se realiza e integra de manera continua dentro de la misma rama del Ticket Principal.
- **Trazabilidad en Commits:** Los commits deben usar como identificador base el ID del Ticket Principal (`feat : PROJ-101 - ...`). De forma opcional y recomendada para mayor granularidad, se puede agregar el ID de la subtarea: `feat : PROJ-101_(T102) - <descripcion>`.
- **Documentación en el PR:** En la plantilla de Pull Request, bajo `## Tickets relacionados`, se debe incluir obligatoriamente el enlace al Ticket Principal de la historia y listar los enlaces de todas las subtareas FE implementadas.

### 1.2 Regla de Identificación mediante Prefijos (FE / BE vs. Historia Principal)
En caso de duda sobre cuál es el Ticket Principal frente a las subtareas al inspeccionar los archivos del directorio o tareas en ClickUp, utilizar la siguiente regla basada en prefijos de nomenclatura:

1. **Subtareas:** Siempre llevan el prefijo correspondiente a su ámbito técnico:
   - **`FE - <Nombre>`** (o `FE: ...`, `Frontend - ...`): Indica que es una **Subtarea de Frontend** (alcance de desarrollo).
   - **`BE - <Nombre>`** (o `BE: ...`, `Backend - ...`): Indica que es una **Subtarea de Backend** (solo contexto técnico de APIs/DB).
2. **Historia Principal (Story):**
   - **NO lleva prefijo `FE` ni `BE`**. Su título describe el módulo o funcionalidad completa a nivel de negocio (ej. `PROJ - Integraciones - Conector de datos - ERP`).
   - Coincide con el nombre de la carpeta contenedora y con el archivo markdown principal que lista la tabla de subtareas.
   - **Es sobre este ticket donde se debe crear la rama Git y el PR por defecto.**
3. **Prerrequisitos:** Llevan el prefijo `PREVIUS TICKET NEEDED <Nombre>` y corresponden a tickets bloqueantes ("blocked by") previos.

---

## 2. Cumplimiento de Arquitectura (DDD y Arquitectura Hexagonal)

Todo desarrollo debe respetar estrictamente la **Arquitectura Hexagonal (Puertos y Adaptadores)** combinada con los principios de **Domain-Driven Design (DDD)** adoptados en los proyectos:

### 2.1 Estructura en Frontend (Angular / TypeScript)
El código debe organizarse respetando la separación en capas desacopladas y la regla de inversión de dependencias:

1. **Dominio (`domain` / `core`):**
   - Entidades de negocio, modelos de datos puros y *Value Objects*.
   - Definición de **Puertos** (interfaces de repositorios o contratos de servicios).
   - *Regla estricta:* Totalmente desacoplado de frameworks UI (`@Injectable`, `HttpClient`), librerías de UI o dependencias externas.
2. **Aplicación (`application` / `use-cases`):**
   - Casos de uso y lógica de aplicación.
   - Orquesta los puertos de dominio para ejecutar operaciones del negocio.
3. **Infraestructura (`infrastructure` / `adapters`):**
   - Implementaciones concretas de los puertos (*Adapters*).
   - Servicios HTTP (`HttpClient`) que consumen las APIs REST del backend (con base en los contratos documentados en las subtareas `BE - ...`).
   - Mapeadores (*mappers* / *adapters*) que transforman los DTOs de la API a entidades del Dominio y viceversa.
   - Persistencia local (localStorage, cookies) y servicios externos.
4. **Presentación / UI (`presentation` / `ui`):**
   - Componentes siguiendo el patrón Container (Smart) y Presentational (Dumb).
   - Formularios, pipes, directivas, guards y diseño visual.
   - Gestión reactiva del estado consumiendo únicamente casos de uso o servicios de aplicación, nunca clientes HTTP directamente.

> [!IMPORTANT]
> **Regla de Dependencias DDD:** Las capas externas (Presentación e Infraestructura) dependen de las capas internas (Dominio y Aplicación). El Dominio jamás conoce ni depende de la UI ni de la Infraestructura.

### 2.2 Proyectos Backend (cuando aplique)
Si se solicita explícitamente intervenir en backend, se debe cumplir con la misma arquitectura hexagonal / DDD:
- Núcleo de Dominio con entidades ricas y contratos de repositorio.
- Casos de uso de aplicación encapsulando la lógica de negocio.
- Adaptadores de infraestructura para controladores HTTP, ORM / persistencia en base de datos y clientes externos.

---

## 3. Directrices de Pruebas y Testing (Unitarias y E2E)

### 3.1 Prohibición de archivos de prueba (`.spec.ts`) en `/core`
- **Regla estricta:** **NO agregar archivos de pruebas unitarias o especificaciones (`*.spec.ts`) dentro del directorio `/core`** (o `src/app/core/` y sus subcarpetas).
- La capa `/core` representa el núcleo de dominio y contratos; debe mantenerse limpia, agnóstica y libre de archivos spec.
- Las pruebas unitarias deben ubicarse en las capas correspondientes de implementación (componentes, servicios de aplicación, adaptadores de infraestructura o módulos funcionales), pero nunca dentro de `/core`.

### 3.2 Pruebas E2E: Simplicidad y Enfoque en lo Esencial
- **No sobrecomplicar con E2E:** No diseñar suites end-to-end exhaustivas, excesivamente largas o frágiles con combinaciones infinitas de casos borde que ralenticen el CI o requieran mantenimiento innecesario.
- **Versión simplificada y esencial:** Agregar **únicamente una versión simplificada de las pruebas E2E estrictamente requeridas** para los cambios introducidos por el ticket.
- **Enfoque clave:** Validar el flujo crítico del usuario ("happy path" principal de la nueva pantalla, componente o acción clave). Casos de validación puntual o lógica condicional deben cubrirse a nivel unitario o de integración.

---

## 4. Flujo de trabajo recomendado

1. Leer el contexto mínimo necesario antes de editar.
2. Identificar el **Ticket Principal de ClickUp (`PROJ-<####>`)** y sus subtareas correspondientes.
3. **Verificar el ámbito de las tareas:**
   - Subtareas **FE**: planificar e implementar en el proyecto frontend.
   - Subtareas **BE**: utilizar únicamente como especificación de contrato API para los adaptadores de infraestructura frontend.
4. **Crear o verificar la rama de trabajo por defecto para la Historia Principal** (`feature/PROJ-<####>-<Descripción>`), evitando crear ramas aisladas por subtarea.
5. Ubicar el módulo, servicio o capa correcta dentro del proyecto respetando la **Arquitectura Hexagonal / DDD** (Dominio, Aplicación, Infraestructura, Presentación).
6. Si el cambio toca funcionalidad crítica o modifica una cantidad de archivos superior a 3, generar un plan de trabajo y pedir confirmación del usuario antes de ejecutar cambios.
7. Hacer cambios consistentes con el patrón existente en el repositorio.
8. **Validar con pruebas:**
   - Respetar la regla de **cero archivos `.spec.ts` en `/core`**.
   - Si se requieren pruebas E2E, mantenerlas **simplificadas y limitadas al flujo esencial** introducido por el cambio.
   - Validar con linter y compilación local.
9. Realizar commits referenciando el Ticket Principal (`feat : PROJ-101 - ...` o `feat : PROJ-101_(T102) - ...`).
10. **Abrir el Pull Request para la Historia Principal**, utilizando obligatoriamente la plantilla de PR del repositorio, titulándolo con el ID principal y listando todas las subtareas FE en `## Tickets relacionados`.
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
     - Lista de enlaces a las **Subtareas FE implementadas** (ej. `Subtarea FE: https://app.clickup.com/t/...`).
   - **`## Cambios realizados`**: Detallar qué componentes, servicios o adaptadores se agregaron o modificaron.
   - **`## Checklist`**: Marcar las casillas correspondientes:
     - [ ] Código probado localmente
     - [ ] Tests unitarios agregados/actualizados (sin archivos .spec en /core)
     - [ ] Tests E2E simplificados/esenciales agregados (si aplica)
     - [ ] Documentación actualizada
     - [ ] Sin breaking changes
   - **`## Cómo probarlo`**: Pasos secuenciales y reproducibles para validar el PR.
   - **`## Screenshots / Evidencias (opcional)`**: Adjuntar capturas, logs o videos si aplica.
   - **`## Notas adicionales`**: Registrar riesgos, dependencias o decisiones de diseño tomadas.

3. **Trazabilidad y vinculación con ClickUp:**
   - Asegurarse de que el PR esté asociado a la tarea de ClickUp (vía título, rama o vinculación manual en ClickUp).
   - Documentar la URL del PR generado en el ticket de ClickUp y notificar al revisor técnico asignado.
