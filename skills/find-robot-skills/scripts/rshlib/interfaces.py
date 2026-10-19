"""Language-independent executable interface v1; data validation only."""
import math

LEVELS={0:'computational_primitive',1:'motion_or_control_primitive',2:'task',3:'workflow'}
KINDS={'algorithm','controller','sensing','trajectory_generator','task','workflow'}
SCHEMA_KEYS={'type','required','properties','items','additionalProperties','minimum','maximum','minItems','maxItems','enum','maxLength','description','x-unit','x-frame','x-order'}


def validate_value(value,schema,path='$'):
    kind=schema.get('type')
    predicates={'object':lambda:isinstance(value,dict),'array':lambda:isinstance(value,list),'number':lambda:type(value) in (int,float) and math.isfinite(value),
        'integer':lambda:type(value) is int,'string':lambda:isinstance(value,str),'boolean':lambda:type(value) is bool,'null':lambda:value is None}
    if kind and (kind not in predicates or not predicates[kind]()):raise ValueError(path+': unexpected data type')
    if 'enum' in schema and value not in schema['enum']:raise ValueError(path+': value outside enum')
    if type(value) in (int,float) and (not math.isfinite(value) or value<schema.get('minimum',value) or value>schema.get('maximum',value)):raise ValueError(path+': numeric bounds')
    if isinstance(value,dict):
        if len(value)>32:raise ValueError(path+': object too large')
        for key in schema.get('required',[]):
            if key not in value:raise ValueError(path+'.'+key+': required')
        for key,item in value.items():
            if key not in schema.get('properties',{}) and schema.get('additionalProperties') is False:raise ValueError(path+'.'+key+': unknown field')
            validate_value(item,schema.get('properties',{}).get(key,{}),path+'.'+key)
    elif isinstance(value,list):
        if not schema.get('minItems',0)<=len(value)<=schema.get('maxItems',4096):raise ValueError(path+': array size')
        for i,item in enumerate(value):validate_value(item,schema.get('items',{}),path+'['+str(i)+']')
    elif isinstance(value,str) and len(value)>schema.get('maxLength',4096):raise ValueError(path+': string size')


def validate_data_schema(schema,depth=0):
    if depth>8 or not isinstance(schema,dict) or set(schema)-SCHEMA_KEYS:raise ValueError('Unsupported or unbounded interface schema')
    kind=schema.get('type')
    if kind not in {'object','array','number','integer','string','boolean','null'}:raise ValueError('Interface schema needs an explicit supported type')
    if kind=='object':
        props=schema.get('properties')
        if not isinstance(props,dict) or len(props)>32 or not set(schema.get('required',[]))<=set(props):raise ValueError('Invalid interface object schema')
        if type(schema.get('additionalProperties')) is not bool:raise ValueError('Declare additionalProperties explicitly')
        for child in props.values():validate_data_schema(child,depth+1)
    if kind=='array':
        if type(schema.get('minItems')) is not int or type(schema.get('maxItems')) is not int or not 0<=schema['minItems']<=schema['maxItems']<=4096:raise ValueError('Array bounds required')
        validate_data_schema(schema.get('items'),depth+1)
    if kind in {'number','integer'}:
        if any(type(schema.get(k)) not in (int,float) or not math.isfinite(schema[k]) for k in ['minimum','maximum']) or schema['minimum']>schema['maximum']:raise ValueError('Finite numeric bounds required')
    if 'x-order' in schema and (not isinstance(schema['x-order'],list) or not all(isinstance(x,str) and x for x in schema['x-order'])):raise ValueError('Invalid coordinate order')


def validate_interface(value):
    if not isinstance(value,dict):raise ValueError('Interface must be an object')
    required={'version','kind','abstraction_level','execution_domain','language','input_transport','output_transport','output_selector','conventions','input_schema','output_schema','preconditions','postconditions','failure_codes','composition'}
    if not required<=set(value):raise ValueError('Incomplete executable interface')
    if value['version']!='1' or value['kind'] not in KINDS or type(value['abstraction_level']) is not int or value['abstraction_level'] not in LEVELS:raise ValueError('Unknown interface kind or level')
    if value['execution_domain'] not in {'computation','simulation','hardware'} or value['language'] not in {'python','rust','cpp','other'}:raise ValueError('Explicit execution domain and language required')
    if value['input_transport'] not in {'json_file_or_inline','cli_arguments'} or value['output_transport']!='json_stdout' or value['output_selector'] not in {'root','outputs'}:raise ValueError('Unsupported interface transport')
    conventions=value['conventions']
    if not isinstance(conventions,dict) or any(not isinstance(conventions.get(k),str) or not conventions[k] for k in ['linear_unit','angular_unit','time_unit','coordinate_frame','joint_order','quaternion_order']):raise ValueError('Units, frame and axis conventions required')
    if (conventions['linear_unit'],conventions['angular_unit'],conventions['time_unit'])!=('m','rad','s'):raise ValueError('Interface v1 uses SI m/rad/s')
    for key in ['preconditions','postconditions','failure_codes']:
        if not isinstance(value[key],list) or not value[key] or not all(isinstance(s,str) and 0<len(s)<=1500 for s in value[key]):raise ValueError('Invalid interface '+key)
    for key in ['input_schema','output_schema']:
        validate_data_schema(value[key])
        if value[key]['type']!='object':raise ValueError('Interface inputs and outputs must be objects')
    composition=value['composition']
    if not isinstance(composition,dict) or composition.get('automatic_frame_conversion') is not False or composition.get('automatic_hardware_execution') is not False or not isinstance(composition.get('depends_on'),list):raise ValueError('Explicit non-automatic composition contract required')
    return value


def validate_handoff(value,source,source_field,target,target_field):
    """Validate an actual field transfer; never infer units or transform frames."""
    validate_interface(source);validate_interface(target)
    for key in ['linear_unit','angular_unit','time_unit','coordinate_frame']:
        if source['conventions'][key]!=target['conventions'][key]:raise ValueError('Handoff requires an explicit '+key+' conversion')
    before=source['output_schema']['properties'][source_field]
    after=target['input_schema']['properties'][target_field]
    for key in ['x-unit','x-frame','x-order']:
        if before.get(key)!=after.get(key):raise ValueError('Handoff annotation mismatch: '+key)
    validate_value(value,before);validate_value(value,after)
    return value
