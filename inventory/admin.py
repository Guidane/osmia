from django.contrib import admin

from .models import Attribute, Category, Location, Part, PartAttributeValue, StockMove


class AttributeInline(admin.TabularInline):
    model = Attribute
    extra = 1


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ('__str__', 'parent')
    search_fields = ('name',)
    inlines = [AttributeInline]


@admin.register(Location)
class LocationAdmin(admin.ModelAdmin):
    list_display = ('__str__', 'parent')
    search_fields = ('name',)


class PartAttributeValueInline(admin.TabularInline):
    model = PartAttributeValue
    extra = 0


@admin.register(Part)
class PartAdmin(admin.ModelAdmin):
    list_display = ('part_number', 'name', 'category', 'location', 'quantity_on_hand', 'unit', 'reorder_level', 'is_active')
    list_filter = ('category', 'location', 'is_active')
    search_fields = ('part_number', 'name')
    readonly_fields = ('quantity_on_hand',)
    inlines = [PartAttributeValueInline]


@admin.register(StockMove)
class StockMoveAdmin(admin.ModelAdmin):
    # Moves change stock levels, so they are read-only here; create them in the app.
    list_display = ('created_at', 'part', 'move_type', 'delta', 'task', 'user')
    list_filter = ('move_type',)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
