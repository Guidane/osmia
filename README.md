# Osmia

A modular business app for companies that build and test electrical equipment, built on Django in the spirit of Odoo: separate modules
(Departments, Users, Tasks, Inventory, Assemblies, Budgets, Devices, Harness) that plug into a shared core and extend each other.

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
| `assembly_detail_panels(request, assembly)` | Assembly page | devices (connectors of a "Device" assembly), tasks (tasks that automation rules created for it) |
| `device_detail_panels(request, device)` | Device page | harness (projects that use the device) |
| `order_detail_panels(request, order)` | Order page | tasks (tasks that automation rules created for the order) |
| `budget_costs(budget_ids)` | Budgets | orders (placed and received orders) |
| `budget_detail_panels(request, budget)` | Budget page | orders (the budget's orders) |
| `topbar_items(request)` | Top bar | automations (the 🔔 notifications bell) |

## Modules

- **Departments** (`departments`): the organisation as nested departments (e.g. Operations > Warehouse), as in Waggle V3. A department's page lists its members, including those in sub-departments, and other modules add to it (e.g. its budgets). Creating and editing departments needs the matching permission.
- **Users** (`users`, depends on departments): custom user model with job title, department and phone. Pages for the user list, search, profile, create and edit. Members can edit only their own profile; managers need the `users.change_user` permission to edit others, and only they assign departments.
- **Tasks** (`tasks`, depends on users and departments): tasks have a department (the assignee's, if left blank). Views include a kanban board, filtered list, "My tasks", a Gantt timeline, status, priority, assignee, start/due dates and overdue highlighting. On the Gantt, a task without a start date runs from the day it was created (shown with a striped bar).
- **Inventory** (`inventory`, depends on users and tasks): **parts**, following Waggle V3. Each part has a part number, a nested category (e.g. Hardware > Fasteners) and a nested location (e.g. Warehouse > Aisle 1 > Bin A1). Categories define **attributes** such as thread or material, and each part stores its own value for them. **Look up online** on the part form fills a part's attributes from its part number (see below); it never looks up prices. Stock moves (receipt, issue, count adjustment) set the quantity on hand, you can't issue more than you have, low-stock parts are flagged, and materials can be issued against a task.
- **Assemblies** (`assemblies`, depends on inventory and tasks): an assembly has a type (generic, device, harness or plate stack), a status, a version, and build and usage instructions. Its bill of materials lists parts and/or sub-assemblies. The **revision** goes up automatically when the components or version change, and circular nesting is blocked. The assembly page shows the fully expanded structure, the total parts needed against stock on hand ("stock covers N builds"), where the assembly is used, and its tasks. A task can be linked to an assembly from the task page, or created with **New build task**. The link is stored in this module, so Tasks doesn't depend on Assemblies.
- **Budgets** (`budgets`, depends on users, departments and tasks): nested budgets (e.g. FY2026 > Operations > Warehouse Ops), each with a number, an amount and an optional department, as in Waggle V3. A task is charged to a budget of its own department, from the task page. Spending is whatever those tasks cost, collected from other modules through the `task_costs` hook. So far that means parts issued to the task, at the part's cost on the day of the move, plus the budget's placed and received orders (through `budget_costs`). Spending rolls up through sub-budgets. Pages show the amount, spent, remaining and a usage bar, and warn when a budget is overspent or its sub-budgets add up to more than it has.

- **Devices** (`devices`, depends on users, inventory and assemblies): anything with connectors that takes part in an electrical setup. That covers units we build (a computer, an inverter, ...), test equipment we build to test them, and external equipment (power supplies, electronic loads, meters, ...). A device we build links to its assembly (type "Device") for the bill of materials. Each connector (J01, P01, ...) has a side, an optional physical connector part (its description is shown as the connector type in harnesses) and numbered pins, each with a label and a signal. Devices are created and edited **only here**: add connectors and assign or edit their pins (one at a time with **+ Add pin**, or several at once). Every change to a device's definition is kept as a new version, and an older version can be made current again.
- **Harness** (`harness`, depends on users and devices): the Wire Harness Designer from the stand-alone harness app. Scroll to zoom and drag empty space to pan; projects open centred on their harnesses, and **⌖ Center** centres the view again. Pick a device from the **Place device** dropdown and click the canvas to place it. Then click one connector and another (or **Loop Back**) to wire them pin to pin: each wire's two pins are chosen in the connect popup, and **Match remaining pins by signal** can pair the rest. The **signal rules** (e.g. PWR ↔ PWR, RX ↔ TX) flag wires that aren't allowed. Each harness gets its mating plug (J01 ↔ P01). Click a wire and then **Show pinout** to open its wire table in a popup; it shows each connector's part number, linked to its Part page, and type. Wires carry wire type, AWG, length and verified flags, and the table exports to CSV. Projects are versioned like devices. The designer only reads Osmia's devices and users: it can't create or change a device. **Open in Devices ↗** and **+ New device ↗** open the Devices module, and the designer picks up the changes when you come back to it (or with ↻).
- **Orders** (`orders`, depends on users, inventory and budgets): purchase orders (PO-0001, ...) from a supplier, charged to a budget, with lines of parts, quantities and unit prices. An order goes draft → placed → received (or cancelled); only drafts can be edited, and an order needs lines to be placed. Placed and received orders count as spending on their budget. **Receiving** an order books every line into stock once, at the order's price.
- **Automations** (`automations`, depends on users): rules that do things by themselves. A rule is **When** (a trigger, e.g. "An order is placed") → **If** (optional conditions on the record, e.g. total is more than 500) → **Then** (steps, run in order). Steps are **Create tasks**, **Change a status** (of an order, task or assembly), **Notify people** (in-app, shown by the 🔔 in the top bar) and **Issue / receive stock**. Tasks a rule creates form a group, and **"All tasks created by a rule are done"** triggers a next rule, with `{source}` still pointing at the record the chain started from. The demo chains two rules this way: placing an order creates the check-in tasks, and finishing them receives the order into stock. If any step fails, the rule's other steps are undone (the change that triggered it stays), and the **Run log** shows what every rule did or why it failed. Rules can trigger rules at most 5 deep.

### Images

Parts, stock locations, assemblies, tasks, devices, harness projects and users can have images (e.g. a photo of a shelf or bin, so people can find it). Each location has its own page, showing the parts stored there, its sub-locations and its images. Add them with **+ Add images** on the record's page, or drop image files onto its Images card. Click a thumbnail to open it large. From there you can page through the images (← →), add a caption, **Make cover** or remove it. The first image is the record's cover, shown next to its name in lists (a user's first photo is their profile picture). Harness projects keep theirs on a page of their own, opened with **🖼 Images ↗** in the designer or from the project list.

Uploads are turned upright, scaled down to at most 2000 px, and re-encoded, which drops their metadata (camera, GPS position, ...). Each file can be up to 20 MB, as JPEG, PNG, GIF, WebP, BMP or TIFF. Files are stored under `media/` (or `OSMIA_MEDIA_ROOT`) and are served by Osmia to logged-in users only. Anyone logged in can add images to a record, except that only you and user managers can change your photos. To give another model images, add `images = GenericRelation('core.Image')` to it and put `{% load osmia_images %}{% image_gallery record %}` on its page.

### Looking parts up online

The part form's **Look up online** button asks Mouser for the part number and fills the part's attributes whose names
match (for example Manufacturer, Datasheet or Number of Positions). Values you already entered are kept unless you tick
"Replace values I already entered". Attributes the category doesn't have yet can be added to it with one click. Prices
and the description are never filled in.

It needs a free Mouser Search API key (mouser.com → Services → APIs), set before starting the server:

```powershell
$env:OSMIA_MOUSER_API_KEY = "your-key"
.\.venv\Scripts\python manage.py runserver
```

Other suppliers (DigiKey, Nexar, ...) can be added as providers in `inventory/lookup.py`.

### Importing the stand-alone harness app's data

```powershell
.\.venv\Scripts\python manage.py import_harness_devices "C:\path\to\harness"   # Devices module: the devices
.\.venv\Scripts\python manage.py import_harness "C:\path\to\harness"           # Harness module: projects, signal rules
```

The first command (Devices module) imports every device with all its versions and matches harness users to Osmia users by name; devices already in Osmia are skipped, so it's safe to repeat. The second (Harness module) imports every project and the signal rules. It never creates devices: it links each project to the devices already imported, and stops with a message if any are missing. Run it once, because running it again imports the projects a second time.

## Adding a new module

1. `python manage.py startapp crm`
2. In `crm/apps.py`, subclass `core.modules.OsmiaModuleConfig` and set a `manifest = Module(...)` with a menu.
3. Add `crm/urls.py` (no `app_name` is needed; the namespace is the app label).
4. Optionally add `crm/hooks.py` to contribute widgets or panels, and `crm/demo.py` for demo data.
5. Add `'crm'` to `OSMIA_MODULES`, then run `makemigrations crm` and `migrate`.

### Triggers and actions for automations

A module declares what rules can react to and do in its `hooks.py`, through `core/automation.py`, without depending on Automations:

```python
automation.event('orders.order_placed', 'An order is placed', fields=[Field('supplier', 'Supplier', lambda o: o.supplier)])
automation.emit('orders.order_placed', order)       # when it happens
automation.status_model(Order)                      # "Change a status" can set it (via Order.set_status if defined)

@automation.action('inventory.stock_move', 'Issue / receive stock', params=[Param('part', 'Part', 'part', required=True), ...])
def stock_move(ctx, params):                        # ctx: object, source, rule
    ...
    return 'what was done, for the run log'
```

The rule builder offers every registered trigger and action, with a form for each action's parameters.
