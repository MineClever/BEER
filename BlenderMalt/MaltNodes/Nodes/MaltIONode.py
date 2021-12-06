# Copyright (c) 2020-2021 BNPR, Miguel Pozo and contributors. MIT license. 

import bpy    
from BlenderMalt.MaltNodes.MaltNode import MaltNode
from BlenderMalt.MaltProperties import MaltPropertyGroup

class MaltIOParameter(bpy.types.PropertyGroup):

    def get_parameter_enums(self, context=None):
        types = ['None']
        from BlenderMalt import MaltPipeline
        bridge = MaltPipeline.get_bridge()
        if bridge and self.graph_type in bridge.graphs:
            graph = bridge.graphs[self.graph_type]
            if self.io_type in graph.graph_io.keys():
                if self.is_output:
                    types = graph.graph_io[self.io_type].dynamic_output_types
                else:
                    types = graph.graph_io[self.io_type].dynamic_input_types
        return [(type, type, type) for type in types]
    
    def get_parameter(self):
        try:
            return self.get_parameter_enums().index(tuple(self['PARAMETER']))
        except:
            return 0

    def set_parameter(self, value):
        self['PARAMETER'] = self.get_parameter_enums()[value]

    graph_type : bpy.props.StringProperty()
    io_type : bpy.props.StringProperty()
    is_output : bpy.props.BoolProperty()
    parameter : bpy.props.EnumProperty(items=get_parameter_enums, get=get_parameter, set=set_parameter)

    def draw(self, context, layout, owner):
        layout.label(text='', icon='DOT')
        layout.prop(self, 'name', text='')
        layout.prop(self, 'parameter', text='')

class MaltIONode(bpy.types.Node, MaltNode):
    
    bl_label = "IO Node"

    properties: bpy.props.PointerProperty(type=MaltPropertyGroup)
    is_output: bpy.props.BoolProperty()

    allow_custom_parameters : bpy.props.BoolProperty(default=False)

    def malt_setup(self):
        function = self.get_function()
        if self.first_setup:
            self.name = self.io_type + (' Output' if self.is_output else ' Input')
        
        self.graph_type = self.id_data.graph_type
        self.pass_type = self.io_type
        
        self.allow_custom_parameters = len(self.get_dynamic_parameter_types()) > 0

        inputs = {}
        outputs = {}
        
        if function['type'] != 'void' and self.is_output:
            inputs['result'] = {'type': function['type']}
        for parameter in function['parameters']:
            if parameter['io'] in ['out','inout'] and self.is_output:
                if parameter['io'] == 'inout':
                    if 'meta' not in parameter: parameter['meta'] = {}
                    parameter['meta']['init'] = parameter['name']
                inputs[parameter['name']] = parameter
            if parameter['io'] in ['','in','inout'] and self.is_output == False:
                outputs[parameter['name']] = parameter
        
        for parameter in self.get_custom_parameters():
            list = inputs if self.is_output else outputs
            if parameter.name not in list.keys(): #Don't override properties
                list[parameter.name] = {
                    'type': parameter.parameter
                }
        
        self.setup_sockets(inputs, outputs)

    io_type : bpy.props.StringProperty(update=MaltNode.setup)

    custom_parameters : bpy.props.CollectionProperty(type=MaltIOParameter)
    custom_parameters_index : bpy.props.IntProperty()

    def get_function(self):
        graph = self.id_data.get_pipeline_graph()
        return graph.graph_io[self.io_type].function
    
    def get_custom_parameters(self):
        if self.allow_custom_parameters:
            return self.custom_parameters
        else:
            return {}
    
    def get_dynamic_parameter_types(self):
        graph = self.id_data.get_pipeline_graph()
        if self.is_output:
            return graph.graph_io[self.io_type].dynamic_output_types
        else: 
            return graph.graph_io[self.io_type].dynamic_input_types
    
    def is_custom_socket(self, socket):
        parameters = [parameter['name'] for parameter in self.get_function()['parameters']]
        if (socket.name == 'result' and self.is_output) or socket.name in parameters:
            return False
        elif socket.name in self.get_custom_parameters().keys():
            return True
        else:
            return False

    def get_source_socket_reference(self, socket):
        transpiler = self.id_data.get_transpiler()
        io = 'out' if self.is_output else 'in'
        if self.is_custom_socket(socket):
            return transpiler.custom_io_reference(io, self.io_type, socket.name)
        else:
            return transpiler.io_parameter_reference(socket.name, io)
    
    def get_source_code(self, transpiler):
        code = ''
        if self.is_output:
            function = self.get_function()
            for socket in self.inputs:
                if self.is_custom_socket(socket):
                    code += transpiler.asignment(self.get_source_socket_reference(socket),
                        socket.get_source_initialization())
                else:
                    if socket.name == 'result':
                        code += transpiler.declaration(socket.data_type, socket.array_size, None)
                    initialization = socket.get_source_initialization()
                    if initialization:
                        code += transpiler.asignment(socket.get_source_reference(), initialization)

            if function['type'] != 'void':
                code += transpiler.result(self.inputs['result'].get_source_reference())

        return code
    
    def get_source_global_parameters(self, transpiler):
        src = MaltNode.get_source_global_parameters(self, transpiler)
        graph_io = self.id_data.get_pipeline_graph().graph_io[self.io_type]
        try:
            index = graph_io.custom_output_start_index
            shader_type = graph_io.shader_type #TODO: Move to graph.generate_source()
        except:
            index = None
            shader_type = None
        for key, parameter in self.get_custom_parameters().items():
            if parameter.is_output:
                socket = self.inputs[key]
                src += transpiler.custom_output_declaration(socket.data_type, key, index, shader_type, self.io_type)
                index += 1
            else:
                socket = self.outputs[key]
                src += transpiler.global_declaration(parameter.parameter, 0, self.get_source_socket_reference(socket))
        return src
    
    def draw_buttons_ext(self, context, layout):
        if self.allow_custom_parameters:
            def refresh():
                #TODO: Overkill
                for tree in bpy.data.node_groups:
                    if tree.bl_idname == 'MaltTree':
                        tree.reload_nodes()
                        tree.update()
            layout.operator("wm.malt_callback", text='Reload', icon='FILE_REFRESH').callback.set(refresh)
            row = layout.row()
            row.template_list('COMMON_UL_UI_List', '', self, 'custom_parameters', self, 'custom_parameters_index')
            col = row.column()
            def add_custom_socket():
                new_param = self.custom_parameters.add()
                new_param.graph_type = self.id_data.graph_type
                new_param.io_type = self.io_type
                new_param.is_output = self.is_output
                name = f"Custom {'Output' if new_param.is_output else 'Input'}"
                i = 1
                #TODO: Check against default parameters
                while f'{name} {i}' in self.custom_parameters.keys():
                    i += 1
                new_param.name = f'{name} {i}'
            col.operator("wm.malt_callback", text='', icon='ADD').callback.set(add_custom_socket)
            def remove_custom_socket():
                self.custom_parameters.remove(self.custom_parameters_index)
            col.operator("wm.malt_callback", text='', icon='REMOVE').callback.set(remove_custom_socket)

    
classes = [
    MaltIOParameter,
    MaltIONode,
]

def register():
    for _class in classes: bpy.utils.register_class(_class)
    
def unregister():
    for _class in reversed(classes): bpy.utils.unregister_class(_class)

