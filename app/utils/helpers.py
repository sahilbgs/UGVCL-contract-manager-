from app.models import Material, MaterialMapping

def resolve_item_code_from_name(name):
    """Resolves standard UGVCL material name variation to its 10-digit item_code using DB mapping."""
    if not name:
        return None
    name_lower = name.lower().strip()
    
    try:
        # Match exactly first
        mapping = MaterialMapping.query.filter_by(alias=name_lower).first()
        if mapping:
            return mapping.item_code
            
        # Match substring (if alias is contained in the material name)
        # Sort by length desc so longer matches (more specific) take precedence
        mappings = MaterialMapping.query.all()
        sorted_mappings = sorted(mappings, key=lambda x: len(x.alias), reverse=True)
        for m in sorted_mappings:
            if m.alias in name_lower:
                return m.item_code
    except Exception as e:
        print(f"Error resolving item code from DB: {e}")
        
    return None

def find_material_by_code_or_name(item_code, name):
    """Find a Material by item_code first, then fallback to name."""
    if not item_code and name:
        item_code = resolve_item_code_from_name(name)
        
    if item_code:
        m = Material.query.filter_by(item_code=item_code).first()
        if m:
            return m
    return Material.query.filter_by(name=name).first()
