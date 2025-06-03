# Import the OpenROAD library
import openroad
# Import PDN specific module if it's a separate namespace, often accessed via openroad.pdn
# Check OpenROAD documentation/examples for exact structure. Assuming it's under openroad.pdn.
import openroad.pdn

# Initialize the OpenROAD database environment
db = openroad.OpenROAD()

# --- Setup: Read input files ---
# Define file paths - replace with actual paths to your files
lef_files = "../Design/nangate45/lef" # Add all necessary LEF files (libraries, macros)
lib_files =  "../Design/nangate45/lib"# Add all necessary Liberty files
verilog_file = "../Design/1_synth.v"

# Read technology LEF file. This typically sets the database units and layer information.
# Read library LEF files (cell LEFs, macro LEFs)
for lef in lef_files:
    db.read_lef(lef)
# Read Liberty files
for lib in lib_files:
    db.read_lib(lib)

# Read the Verilog gate-level netlist
db.read_verilog(verilog_file)

# Get the top level block (design) after reading Verilog
block = db.get_top_block()
if block is None:
    print("Error: Could not get top block after reading Verilog.")
    # Exit the script gracefully or handle the error
    exit(1)

# Set the current design block to operate on
db.set_current_design(block)

# --- Timing Setup ---
# Define the clock net and period
clock_port_name = "clk" # User specified clock port name
clock_period_ns = 50.0 # Clock period in nanoseconds

# Create the clock object in the timing database
# Find the clock port object in the design block
clock_port = block.findPort(clock_port_name)
if clock_port is None:
     print(f"Error: Clock port '{clock_port_name}' not found in the design.")
     # Exit the script gracefully or handle the error
     exit(1)

# Create the primary clock constraint
db.create_clock(
    name="main_clock",        # Internal name for the clock
    period=clock_period_ns,   # Clock period in nanoseconds
    ports=[clock_port]        # List of clock port objects associated with this clock
)

# --- Floorplanning ---
# Define the bounding box for the die area (bottom-left x, bottom-left y, top-right x, top-right y)
die_lx, die_by, die_rx, die_ty = 0, 0, 40, 60
# Define the bounding box for the core area
core_lx, core_by, core_rx, core_ty = 10, 10, 30, 50

# Initialize the floorplan with the specified die and core boundaries
# Coordinates are expected in database units (DBUs), typically set by the tech LEF.
# Assuming the provided values (0,0,40,60 etc.) are already in DBUs or the API handles conversion.
db.init_floorplan(
    die_area=[die_lx, die_by, die_rx, die_ty],
    core_area=[core_lx, core_by, core_rx, core_ty]
)

# --- Placement Constraints (Apply before placement) ---
# Set a fence region to constrain macro placement
fence_lx, fence_by, fence_rx, fence_ty = 15, 10, 30, 40 # Fence region coordinates in DBUs
# Coordinates are expected in DBUs. Assuming provided values (15,10,30,40) are in DBUs.
db.set_macro_fence(fence=[fence_lx, fence_by, fence_rx, fence_ty])

# Set minimum spacing between macros
macro_min_spacing = 5.0 # Minimum spacing in database units (assuming um = DBU here for simplicity)
db.set_macro_spacing(macro_min_spacing)

# Set a halo region around each macro
macro_halo = 5.0 # Halo size in database units (assuming um = DBU here)
# Apply uniform halo on all sides (left, bottom, right, top)
db.set_macro_halo(halo=[macro_halo, macro_halo, macro_halo, macro_halo])

# --- Placement ---
# Perform initial placement (primarily places macros according to floorplan and constraints)
# This step also typically performs initial global cell placement for standard cells.
db.init_placement()

# Perform global placement (optimizes standard cell placement globally)
global_placement_iterations = 20 # Number of iterations for global placement
db.global_placement(iterations=global_placement_iterations)

# Perform detailed placement (local legalization and optimization of standard cells)
detailed_placement_max_disp_x = 0.5 # Maximum displacement in X direction (DBUs)
detailed_placement_max_disp_y = 0.5 # Maximum displacement in Y direction (DBUs)
db.detailed_placement(
    max_displacement_x=detailed_placement_max_disp_x,
    max_displacement_y=detailed_placement_max_disp_y
)

# --- Clock Tree Synthesis (CTS) ---
# Specify the clock buffer cell name from the library
clock_buffer_cell_name = "BUF_X2" # User specified buffer cell
# Specify unit resistance and capacitance for clock and signal wires
# These values should be in resistance/capacitance per database unit length.
# Assuming the provided values are per um if DBUs are um.
wire_resistance_per_unit = 0.03574
wire_capacitance_per_unit = 0.07516

# Perform clock tree synthesis
db.clock_tree_synthesis(
    buffer_cell=clock_buffer_cell_name,
    resistance_per_unit_length=wire_resistance_per_unit,
    capacitance_per_unit_length=wire_capacitance_per_unit
    # Additional CTS options (e.g., target skew, max capacitance, insertion delay) can be added here.
)

# --- Power Distribution Network (PDN) Generation ---
# Define the rules for power grid construction based on user request.
# Widths, spacings, pitches, and offsets are specified in database units (DBUs).
# Assuming the provided values (um) match the DBUs or are automatically scaled.

# M1 pitch was not specified by user. Using 1.0 um as a placeholder value.
# Spacing for M1 is derived from the assumed pitch and the given width: spacing = pitch - width.
m1_grid_pitch_um = 1.0
m1_grid_spacing_um = m1_grid_pitch_um - 0.07 # Using width 0.07 specified for M1

pdn_rules = [
    # Power rings on M7 around the core area for standard cells
    {
        "type": "ring",
        "layers": ["M7"],
        "widths": [4.0],
        "spacings": [4.0],
        "offset": 0.0, # Offset from the boundary
        "extend_to_die": False, # Do not extend rings to the die boundary
        "extend_to_core": True, # Extend rings to the core boundary
    },
    # Power rings on M8 around the core area for standard cells
    {
        "type": "ring",
        "layers": ["M8"],
        "widths": [4.0],
        "spacings": [4.0],
        "offset": 0.0, # Offset from the boundary
        "extend_to_die": False,
        "extend_to_core": True,
    },
    # Power grids on M1 for standard cells (typically Vertical)
    {
        "type": "strip",
        "direction": "vert",
        "layers": ["M1"],
        "widths": [0.07],
        "pitches": [m1_grid_pitch_um], # Assumed pitch
        "spacings": [m1_grid_spacing_um], # Derived spacing based on assumed pitch and width
        "offset": 0.0, # Offset from the start edge
    },
    # Power grids on M4 for macros (typically Horizontal)
    {
        "type": "strip",
        "direction": "horiz",
        "layers": ["M4"],
        "widths": [1.2],
        "spacings": [1.2],
        "pitches": [6.0],
        "offset": 0.0, # Offset from the start edge
    },
     # Power grids on M7 (Vertical) - based on user specifying width/spacing/pitch for M7 grids
     {
        "type": "strip",
        "direction": "vert", # Assuming vertical based on typical layer stack direction preference
        "layers": ["M7"],
        "widths": [1.4],
        "spacings": [1.4],
        "pitches": [10.8],
        "offset": 0.0,
    },
    # Macro specific PDN components (if macros exist)
    # Power rings on M5
    {
        "type": "ring",
        "layers": ["M5"],
        "widths": [1.5],
        "spacings": [1.5],
        "offset": 0.0,
         "extend_to_die": False,
        "extend_to_core": True, # Rings around core area (or encompassing macro region)
    },
     # Power rings on M6
     {
        "type": "ring",
        "layers": ["M6"],
        "widths": [1.5],
        "spacings": [1.5],
        "offset": 0.0,
         "extend_to_die": False,
        "extend_to_core": True,
    },
    # Power grids on M5 (Vertical)
    {
        "type": "strip",
        "direction": "vert", # Assuming vertical
        "layers": ["M5"],
        "widths": [1.2],
        "spacings": [1.2],
        "pitches": [6.0],
        "offset": 0.0,
    },
     # Power grids on M6 (Horizontal)
     {
        "type": "strip",
        "direction": "horiz", # Assuming horizontal
        "layers": ["M6"],
        "widths": [1.2],
        "spacings": [1.2],
        "pitches": [6.0],
        "offset": 0.0,
    },
]

# Create the power grid using the defined rules
# The create_power_grid function expects floating-point values for widths, spacings, pitches, offsets in DBUs.
# Assuming um = DBU implicitly here.
openroad.pdn.create_power_grid(
    db,
    "design_pdn", # A name for the generated PDN
    pdn_rules,    # The list of rule dictionaries defining the PDN structure
    via_pitch_parallel=0.0, # Set via pitch between parallel grids to 0
    offset=0.0 # Set global offset for all PDN features to 0
    # Note: Power/Ground nets (VDD, GND) are typically automatically assigned based on library definitions
    # unless specified otherwise in the PDN rules or design.
)


# --- Routing ---
# Set the minimum and maximum layers for routing
min_route_layer_name = "M1" # User specified minimum layer
max_route_layer_name = "M7" # User specified maximum layer

# Perform global routing within the specified layer range
db.global_routing(
    min_layer=min_route_layer_name, # Minimum layer name for routing
    max_layer=max_route_layer_name  # Maximum layer name for routing
)

# Perform detailed routing (cleans up global routes, creates vias, handles DRCs)
# Detailed routing typically operates within the same layer range defined for global routing
# unless explicitly specified otherwise.
db.detailed_routing()


# --- Analysis ---
# Perform static IR drop analysis
ir_drop_analysis_layers = ["M1"] # Layers to analyze for IR drop, user specified M1
# Assuming power and ground net names are "VDD" and "GND" based on common practice
power_nets_for_irdrop = ["VDD"]
ground_nets_for_irdrop = ["GND"]

# Run the IR drop analysis
db.ir_drop_analysis(
    power_nets=power_nets_for_irdrop,
    ground_nets=ground_nets_for_irdrop,
    layers=ir_drop_analysis_layers
    # Other IR drop options (e.g., analysis modes, reporting format, output file) can be added here.
)


# --- Output ---
# Write the final design database state to a DEF file
output_def_file_name = "final.def" # User specified output file name
db.write_def(output_def_file_name)

# Script execution finishes. The design is saved in final.def

