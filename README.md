# Osmia

A modular business app for companies that build and test electrical equipment, built on Django in the spirit of Odoo: separate modules
(Users, Tasks, Inventory, Assemblies, Budgets, Devices, Harness) that plug into a shared core and extend each other.

## Quick start (Windows PowerShell)

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.txt
.\.venv\Scripts\python manage.py migrate
.\.venv\Scripts\python manage.py load_demo     # optional: demo users, departments, tasks, parts, assemblies, budgets
.\.venv\Scripts\python manage.py runserver
```

Open http://127.0.0.1:8000 and log in as **admin / admin** (demo users `alice`, `bob`, `carla` use password `demo`).
Run the tests with `.\.venv\Scripts\python manage.py test`.

## How the module system works

| Piece | Where | What it does |
|---|---|---|
| Manifest | `<module>/apps.py` | `manifest = Module(title, icon, depends, menu, sequence)`, which works like Odoo's `__manifest__.py` |
| Registry | `core/modules.py` | Finds installed modules, orders them by dependency, mounts each `<module>/urls.py` at `/<label>/` under the namespace `<label>` |
| Hooks | `core/hooks.py`, `<module>/hooks.py` | Extension points that let modules add to each other's pages without importing each other |
| Layout | `core/templates/base.html` | Top bar with the current module's menu and a module switcher, both built from the manifests |
| Demo data | `<module>/demo.py` | `manage.py load_demo` calls each module's `load()` in dependency order |

Modules are enabled in `OSMIA_MODULES` in `osmia/settings.py`. If a module's
dependency is missing, startup stops with a clear error.

### Built-in hooks

| Hook | Called by | Contributed by |
|---|---|---|
| `dashboard_widgets(request)` | Home dashboard | users, tasks, inventory, assemblies, budgets |
| `user_detail_panels(request, user)` | User page | tasks (open tasks), inventory (recent stock moves) |
| `task_detail_panels(request, task)` | Task page | inventory (materials issued for the task), assemblies (linked assembly and stock shortfalls), budgets (budget the task is charged to) |
| `department_detail_panels(request, department)` | Department page | budgets (the department's budgets) |
| `task_costs(task_ids)` | Budgets | inventory (cost of parts issued to each task) |
| `part_detail_panels(request, part)` | Part page | assemblies (assemblies that use the part), devices (connectors that use the part) |
| `assembly_detail_panels(request, assembly)` | Assembly page | devices (connectors of a "Device" assembly) |
| `device_detail_panels(request, device)` | Device page | harness (projects that use the device) |

## Modules

- **Users** (`users`): custom user model with job title, department and phone. Pages for the user list, search, profile, create and edit. Members can edit only their own profile; managers need the `users.change_user` permission to edit others. **Departments** are nested (e.g. Operations > Warehouse), as in Waggle V3. Only managers assign them, and a department's page lists its members, including those in sub-departments.
- **Tasks** (`tasks`, depends on users): tasks have a department (the assignee's, if left blank). Views include a kanban board, filtered list, "My tasks", a Gantt timeline, status, priority, assignee, start/due dates and overdue highlighting. On the Gantt, a task without a start date runs from the day it was created (shown with a striped bar).
- **Inventory** (`inventory`, depends on users and tasks): **parts**, following Waggle V3. Each part has a part number, a nested category (e.g. Hardware > Fasteners) and a nested location (e.g. Warehouse > Aisle 1 > Bin A1). Categories define **attributes** such as thread or material, and each part stores its own value for them. Parts can have an **interconnect** family and gender, and the part page lists the parts it mates with. Stock moves (receipt, issue, count adjustment) set the quantity on hand, you can't issue more than you have, low-stock parts are flagged, and materials can be issued against a task.
- **Assemblies** (`assemblies`, depends on inventory and tasks): an assembly has a type (generic, device, harness or plate stack), a status, a version, and build and usage instructions. Its bill of materials lists parts and/or sub-assemblies. The **revision** goes up automatically when the components or version change, and circular nesting is blocked. The assembly page shows the fully expanded structure, the total parts needed against stock on hand ("stock covers N builds"), where the assembly is used, and its tasks. A task can be linked to an assembly from the task page, or created with **New build task**. The link is stored in this module, so Tasks doesn't depend on Assemblies.
- **Budgets** (`budgets`, depends on users and tasks): nested budgets (e.g. FY2026 > Operations > Warehouse Ops), each with a number, an amount and an optional department, as in Waggle V3. A task is charged to a budget of its own department, from the task page. Spending is whatever those tasks cost, collected from other modules through the `task_costs` hook. So far that means parts issued to the task, at the part's cost on the day of the move. Spending rolls up through sub-budgets. Pages show the amount, spent, remaining and a usage bar, and warn when a budget is overspent or its sub-budgets add up to more than it has.

- **Devices** (`devices`, depends on users, inventory and assemblies): anything with connectors that takes part in an electrical setup. That covers units we build (a computer, an inverter, ...), test equipment we build to test them, and external equipment (power supplies, electronic loads, meters, ...). A device we build links to its assembly (type "Device") for the bill of materials. Each connector (J01, P01, ...) has a side, an optional physical connector part (which gives its interconnect family/gender) and numbered pins, each with a label, a signal and an optional pin set (e.g. a PWR/GND pair). Every change to a device's definition is kept as a new version, and an older version can be made current again.
- **Harness** (`harness`, depends on users and devices): the Wire Harness Designer from the stand-alone harness app. Place devices from the library on a canvas, then connect connector to connector: each harness gets its mating connector (J01 ↔ P01), and pins are paired by pin set and by the **signal rules** (e.g. PWR ↔ PWR, RX ↔ TX). Wires carry AWG, twist/shield and a verified flag, which the device's owner ticks. Projects are versioned like devices. The designer uses Osmia's devices and users; editing a device in the designer updates it in Devices too.

### Importing the stand-alone harness app's data

```powershell
.\.venv\Scripts\python manage.py import_harness "C:\path\to\harness"
```

This imports every device (with all versions), every project (with device references re-pointed) and the signal rules. Harness users are matched to Osmia users by name. Run it once: running it again imports everything a second time.

## Adding a new module

1. `python manage.py startapp crm`
2. In `crm/apps.py`, subclass `core.modules.OsmiaModuleConfig` and set a `manifest = Module(...)` with a menu.
3. Add `crm/urls.py` (no `app_name` is needed; the namespace is the app label).
4. Optionally add `crm/hooks.py` to contribute widgets or panels, and `crm/demo.py` for demo data.
5. Add `'crm'` to `OSMIA_MODULES`, then run `makemigrations crm` and `migrate`.
