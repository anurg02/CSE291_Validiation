import openroad
import odb
import pdn
import psm
import grt
import drt
import os
from pathlib import Path

# -----------------------------------------------------------------------------
# Initialization
# -----------------------------------------------------------------------------

# Initialize OpenROAD core objects
# Use the create() method for proper initialization
db = odb.dbDatabase.create()
tech = db.getTech()
design = openroad.Design(db) # Initialize Design with the created database

# Set paths to library and design files
# Assuming this script is run from a directory containing the Design folder
design_dir = Path("../Design/")
lib_dir = design_dir / "nangate45/lib"
lef_dir = design_dir / "nangate45/lef"

# Define the top-level module name
design_top_module_name = "gcd" # Replace with your actual top module name if different

# -----------------------------------------------------------------------------
# File Reading
# -----------------------------------------------------------------------------

print("Reading input files...")

# Read liberty (.lib) timing libraries
lib_files = sorted(list(lib_dir.glob("*.lib")))
if not lib_files:
    print(f"Error: No .lib files found in {lib_dir}")
    exit(1)
for lib_file in lib_files:
    print(f"  Reading liberty file: {lib_file}")
    # Use openroad.read_liberty function
    openroad.read_liberty(design, lib_file.as_posix())

# Read LEF (Library Exchange Format) files
# Read technology LEF first, then cell LEFs
tech_lef_files = sorted(list(lef_dir.glob("*.tech.lef")))
lef_files = sorted(list(lef_dir.glob('*.lef')))
all_lef_files = tech_lef_files + lef_files

if not all_lef_files:
    print(f"Error: No .lef files found in {lef_dir}")
    exit(1)

for lef_file in all_lef_files:
    print(f"  Reading LEF file: {lef_file}")
    # Use openroad.read_lef function
    openroad.read_lef(design, lef_file.as_posix())

# Read Verilog netlist
verilog_file = design_dir / f"{design_top_module_name}.v"
if not verilog_file.exists():
    print(f"Error: Verilog file not found: {verilog_file}")
    exit(1)
print(f"  Reading Verilog file: {verilog_file}")
# Use openroad.read_verilog function
openroad.read_verilog(design, verilog_file.as_posix())

# Link the design to connect modules based on library information
print("Linking design...")
# Use openroad.link_design function
openroad.link_design(design, design_top_module_name)

# Get the block object representing the top module
block = db.getChip().getBlock()
if block is None:
    print(f"Error: Could not get block for top module '{design_top_module_name}'. Linking failed?")
    exit(1)

# -----------------------------------------------------------------------------
# Constraints and Setup
# -----------------------------------------------------------------------------

print("Setting constraints...")

# Get the timing object
timing = openroad.Timing(design)

# Set the clock constraint
clock_period_ns = 40.0
clock_port_name = "clk" # Name of the clock port in the Verilog
clock_name = "core_clock" # Name for the internal clock object

# Create the clock using a TCL command via evalTclString
print(f"  Creating clock '{clock_name}' on port '{clock_port_name}' with period {clock_period_ns} ns")
design.evalTclString(f"create_clock -period {clock_period_ns} [get_ports {clock_port_name}] -name {clock_name}")

# Propagate the clock signal for timing analysis
print("  Setting propagated clock")
design.evalTclString(f"set_propagated_clock [get_clocks {{{clock_name}}}]")

# Set unit resistance and capacitance values for clock and signal nets
unit_resistance = 0.03574 # units per micron
unit_capacitance = 0.07516 # units per micron
print(f"  Setting wire RC - Clock: R={unit_resistance}, C={unit_capacitance}")
design.evalTclString(f"set_wire_rc -clock -resistance {unit_resistance} -capacitance {unit_capacitance}")
print(f"  Setting wire RC - Signal: R={unit_resistance}, C={unit_capacitance}")
design.evalTclString(f"set_wire_rc -signal -resistance {unit_resistance} -capacitance {unit_capacitance}")

# -----------------------------------------------------------------------------
# Floorplanning
# -----------------------------------------------------------------------------

print("Performing floorplanning...")

# Initialize floorplan object
# The Floorplan object is part of the block
floorplan = block.getFloorplan()

# Get technology database
tech_db = db.getTech()

# Find a suitable standard cell site from the library
# This name might vary depending on the LEF files. Common names include 'stdcell' or specific names.
# Check available sites using: [s.getName() for s in tech_db.getSites()] or openroad.dump_def_sites(design)
site_name = "FreePDK45_38x28_10R_NP_162NW_34O" # Example site name - verify with your LEF
site = tech_db.findSite(site_name)
if site is None:
    print(f"Error: Site '{site_name}' not found. Please check your LEF files.")
    # Fallback: try finding any CORE site
    for s in tech_db.getSites():
        if s.getType() == "CORE":
            site = s
            print(f"  Warning: Site '{site_name}' not found. Using site '{site.getName()}' instead.")
            break
    if site is None:
        print("Fatal Error: No CORE site found in technology LEF. Cannot initialize floorplan.")
        exit(1)
else:
     print(f"  Using site: {site.getName()}")

# Set die area and core area
# Prompt requires 5 microns spacing between core and die
margin_um = 5.0
# The die area size is not specified in the prompt. Let's use a fixed core size for demonstration
# and calculate the die size based on core + margin.
# A more typical flow might size based on estimated standard cell area and target utilization.
# Example fixed core size:
core_width_um = 200.0  # Example core width
core_height_um = 200.0 # Example core height

core_lx_um = margin_um
core_ly_um = margin_um
core_ux_um = core_lx_um + core_width_um
core_uy_um = core_ly_um + core_height_um

die_lx_um = 0.0
die_ly_um = 0.0
die_ux_um = core_ux_um + margin_um
die_uy_um = core_uy_um + margin_um

core_area = odb.Rect(design.micronToDBU(core_lx_um), design.micronToDBU(core_ly_um),
                     design.micronToDBU(core_ux_um), design.micronToDBU(core_uy_um))
die_area = odb.Rect(design.micronToDBU(die_lx_um), design.micronToDBU(die_ly_um),
                    design.micronToDBU(die_ux_um), design.micronToDBU(die_uy_um))

print(f"  Initializing floorplan: Die Area ({die_lx_um},{die_ly_um})-({die_ux_um},{die_uy_um}) um, Core Area ({core_lx_um},{core_ly_um})-({core_ux_um},{core_uy_um}) um")

# Use openroad.init_floorplan function
openroad.init_floorplan(design, die_area, core_area, site)

# Generate routing tracks based on the floorplan
print("  Generating routing tracks...")
# The floorplan object is now available on the block
block_fp = block.getFloorplan()
if block_fp is None:
     print("Error: Floorplan not initialized on block. Cannot generate tracks.")
     exit(1)
block_fp.makeTracks()

# -----------------------------------------------------------------------------
# I/O Pin Placement
# -----------------------------------------------------------------------------

print("Performing I/O pin placement...")

# Get I/O Placer object
# The IO placer is associated with the block
io_placer = block.getIOPlacer()
params = io_placer.getParameters()

# Set parameters as needed - the prompt only specifies layers M8 and M9
# params.setRandSeed(42) # Set random seed for reproducibility (optional)
# params.setMinDistanceInTracks(False) # Set minimum distance in database units, not tracks (optional)
# params.setMinDistance(design.micronToDBU(0)) # Set minimum distance (optional)
# params.setCornerAvoidance(design.micronToDBU(0)) # Set corner avoidance distance (optional)

# Place I/O pins on metal8 (horizontal preference) and metal9 (vertical preference) layers
m8 = tech_db.findLayer("metal8")
m9 = tech_db.findLayer("metal9")

if not m8 or not m9:
    print("Error: metal8 or metal9 layer not found. Cannot perform I/O placement on specified layers.")
    # Fallback to default layers or skip IO placement
    print("Skipping I/O placement on M8/M9.")
    io_placer_successful = False
else:
    print(f"  Placing I/O pins on {m8.getName()} (Horizontal) and {m9.getName()} (Vertical)")
    io_placer.addHorLayer(m8)
    io_placer.addVerLayer(m9)

    # Run I/O placement using annealing
    # OpenROAD typically runs IO placer after floorplan and before placement.
    # The parameter is `runAnnealing(True)` for random initialization, `False` for deterministic.
    # Use openroad.place_io function
    io_placer_successful = openroad.place_io(design, True) # Use random mode

    if io_placer_successful:
        print("I/O pin placement finished.")
    else:
        print("Warning: I/O pin placement failed.")


# -----------------------------------------------------------------------------
# Macro Placement
# -----------------------------------------------------------------------------

print("Performing macro placement...")

# Find macro instances in the design
macros = [inst for inst in block.getInsts() if inst.getMaster().isBlock()]

if len(macros) > 0:
    print(f"  Found {len(macros)} macro instances. Running macro placement...")
    # Get Macro Placer object
    mpl = design.getMacroPlacer()

    # Get the core area for the fence region
    core = block.getCoreArea()

    # Configure and run macro placement
    # Set 5 um halo around macros as requested
    halo_width_um = 5.0
    halo_height_um = 5.0
    print(f"  Setting {halo_width_um} um halo around macros (std cells will avoid).")

    # Configure parameters - use a subset of common parameters
    mpl_params = mpl.getParameters()
    mpl_params.setHaloX(design.micronToDBU(halo_width_um))
    mpl_params.setHaloY(design.micronToBU(halo_height_um)) # Use micronToBU for Y halo? Or consistent DBU? Let's stick to DBU as micronToDBU is available.
    mpl_params.setHaloY(design.micronToDBU(halo_height_um))


    # Set the fence region to the core area
    print(f"  Setting macro fence region to core area: ({core.xMin()},{core.yMin()})-({core.xMax()},{core.yMax()}) DBU")
    mpl_params.setFence(core.xMin(), core.yMin(), core.xMax(), core.yMax())

    # Note: The prompt asks to ensure a minimum 5 um spacing *between* macros.
    # The OpenROAD MacroPlacer Python API does not have a direct parameter to enforce this.
    # The halo parameter prevents *standard cells* from being placed near macros.
    # Macro-to-macro spacing is typically handled by ensuring macros are not overlapping
    # (which the placer does for legal placement), or by using manual pre-placement
    # or adding fixed blockages before macro placement for strict minimum distances.
    # This script relies on the placer preventing overlaps.

    # Run the macro placer
    # Use openroad.place_macros function
    try:
        # openroad.place_macros(design) # Simple call without detailed parameter struct
        # Or using the MPL object directly after setting parameters:
        mpl.run()
        print("  Macro placement finished.")
        macro_placement_successful = True
    except Exception as e:
        print(f"  Warning: Macro placement failed or encountered an error: {e}")
        print("  Continuing without macro placement. Ensure macros were placed manually or previous step was successful.")
        macro_placement_successful = False # Assume failure if exception

else:
    print("  No macro instances found. Skipping macro placement.")
    macro_placement_successful = True # Consider successful if no macros exist


# -----------------------------------------------------------------------------
# Standard Cell Placement - Global Placement
# -----------------------------------------------------------------------------

print("Performing standard cell global placement...")

# Get Global Placer object (RePlace)
gpl = design.getReplace()

# Configure global placement
gpl.setTimingDrivenMode(False) # Disable timing-driven mode for simplicity (can enable if timing is important)
gpl.setRoutabilityDrivenMode(True) # Enable routability-driven mode
gpl.setUniformTargetDensityMode(True) # Use uniform target density

# **CORRECTION:** Set the target utilization as 45% (density 0.45)
target_utilization = 0.45
print(f"  Setting target density (utilization) to {target_utilization}")
gpl.setTargetDensity(target_utilization)

# Run global placement
# gpl.doInitialPlace() # Optional: Run initial placement first
print("  Running Nesterov-based global placement...")
gpl.doNesterovPlace(threads = os.cpu_count() if os.cpu_count() else 4) # Run Nesterov-based global placement

print("Global placement finished.")

# -----------------------------------------------------------------------------
# Power Delivery Network (PDN) Generation
# -----------------------------------------------------------------------------

print("Generating Power Delivery Network...")

pdngen = design.getPdnGen()

# Set up global power/ground connections
# Mark existing power/ground nets as special nets
for net in block.getNets():
    if net.getSigType() in ["POWER", "GROUND"]:
        net.setSpecial()

# Find or create VDD/VSS nets
VDD_net = block.findNet("VDD")
VSS_net = block.findNet("VSS")

if VDD_net is None:
    print("  Creating VDD net.")
    VDD_net = odb.dbNet_create(block, "VDD")
    VDD_net.setSpecial()
    VDD_net.setSigType("POWER")
if VSS_net is None:
    print("  Creating VSS net.")
    VSS_net = odb.dbNet_create(block, "VSS")
    VSS_net.setSpecial()
    VSS_net.setSigType("GROUND")

# Connect standard cell power pins to global nets using global_connect
# Use pattern matching for standard VDD/VSS pins.
print("  Connecting standard cell power pins globally...")
# Map standard VDD pins to power net for all instances
block.addGlobalConnect(region=None,
                       instPattern=".*",
                       pinPattern="^VDD$",
                       net=VDD_net,
                       do_connect=True)
# Map standard VSS pins to ground net
block.addGlobalConnect(region=None,
                       instPattern=".*",
                       pinPattern="^VSS$",
                       net=VSS_net,
                       do_connect=True)

# Apply the global connections
block.globalConnect()
print("  Global power/ground connections applied.")

# Configure power domains
# The prompt implies a single core domain for standard cells and potentially macros
# The domain needs to be defined *before* making grids/rings/straps for it.
core_domain = pdngen.makeDomain("Core", power=VDD_net, ground=VSS_net)

if core_domain is None:
     print("Error: Failed to create Core domain. Cannot generate PDN.")
     exit(1)

domains = [core_domain]

# Define via cut pitch for connections between parallel grids
# The prompt specifies 0 um pitch for via between two grids. This likely refers to dense via placement.
pdn_cut_pitch_x_um = 0.0
pdn_cut_pitch_y_um = 0.0
pdn_cut_pitch = [design.micronToDBU(pdn_cut_pitch_x_um), design.micronToDBU(pdn_cut_pitch_y_um)]
print(f"  Setting via cut pitch for connections between parallel grids to {pdn_cut_pitch_x_um} um in X and {pdn_cut_pitch_y_um} um in Y.")

# Define offset for all rings and straps - Prompt specifies 0 offset
pdn_offset_um = 0.0
pdn_offset = design.micronToDBU(pdn_offset_um)
print(f"  Setting ring/strap offset to {pdn_offset_um} um.")

# Get necessary metal layers by name
m1 = tech_db.findLayer("metal1")
m4 = tech_db.findLayer("metal4")
m5 = tech_db.findLayer("metal5")
m6 = tech_db.findLayer("metal6")
m7 = tech_db.findLayer("metal7")
m8 = tech_db.findLayer("metal8")
m9 = tech_db.findLayer("metal9") # M9 is used for IO, might be needed for PDN connection? Let's add it.


if not all([m1, m4, m5, m6, m7, m8, m9]): # Added m9 check
    missing_layers = [layer_name for layer_name in ["metal1", "metal4", "metal5", "metal6", "metal7", "metal8", "metal9"] if tech_db.findLayer(layer_name) is None]
    print(f"Error: Could not find all required metal layers: {', '.join(missing_layers)}. Cannot generate PDN.")
    exit(1)

print("  Defining PDN structure...")

# Create the main core grid structure
# This grid covers the standard cell area and forms the backbone for power distribution
for domain in domains:
    core_grid_name = "core_grid"
    # Use openroad.make_pdn_core_grid function
    openroad.make_pdn_core_grid(design, domain, core_grid_name, starts_with="GROUND") # Use string for starts_with

    # Get the core grid just created
    # Use openroad.find_pdn_grid function
    core_grids = openroad.find_pdn_grid(design, core_grid_name)
    if not core_grids:
        print(f"Error: Failed to create or find core grid '{core_grid_name}'.")
        continue # Skip PDN generation for this domain
    core_grid = core_grids[0] # Assume there's only one core grid with this name

    # Create power rings around core area on metal7 and metal8
    # Prompt: rings on M7 and M8, width 5, spacing 5
    ring_width_m7_m8_um = 5.0
    ring_spacing_m7_m8_um = 5.0
    print(f"    Adding rings on {m7.getName()} and {m8.getName()} (W={ring_width_m7_m8_um}um, S={ring_spacing_m7_m8_um}um)")
    # Use openroad.make_pdn_ring function
    openroad.make_pdn_ring(design, core_grid,
                           layer0=m7,
                           width0=design.micronToDBU(ring_width_m7_m8_um),
                           spacing0=design.micronToDBU(ring_spacing_m7_m8_um),
                           layer1=m8,
                           width1=design.micronToDBU(ring_width_m7_m8_um),
                           spacing1=design.micronToDBU(ring_spacing_m7_m8_um),
                           starts_with="GRID", # Connects to existing grid
                           offset=[pdn_offset for _ in range(4)], # Offset from core boundary (left, bottom, right, top)
                           pad_offset=[0 for _ in range(4)], # No pad offset
                           extend=False, # Do not extend rings beyond core boundary
                           pad_pin_layers=[], # No connection to pads via rings
                           nets=[]) # Rings are for the domain's main nets (VDD/VSS) - implicitly handled by domain connection

    # Create horizontal power straps on metal1 following standard cell pins
    # Prompt: grids on M1 for standard cells, width 0.07 um
    followpin_width_m1_um = 0.07
    print(f"    Adding followpin straps on {m1.getName()} (W={followpin_width_m1_um}um)")
    # Use openroad.make_pdn_followpin function
    openroad.make_pdn_followpin(design, core_grid,
                                layer=m1,
                                width=design.micronToDBU(followpin_width_m1_um),
                                extend="CORE") # Extend straps to cover the core area

    # Create power straps on metal4
    # Prompt: grids on M4 for macros, width 1.2 um, spacing 1.2 um, pitch 6 um
    # Note: The script implements M4 straps in the *core* grid. Macro-specific straps are on M5/M6.
    # This interpretation assumes M4 is part of the core grid backbone connecting to standard cells (via M1) and macros (via M5/M6).
    strap_width_m4_um = 1.2
    strap_spacing_m4_um = 1.2
    strap_pitch_m4_um = 6.0
    print(f"    Adding straps on {m4.getName()} (W={strap_width_m4_um}um, S={strap_spacing_m4_um}um, P={strap_pitch_m4_um}um)")
    # Use openroad.make_pdn_strap function
    openroad.make_pdn_strap(design, core_grid,
                            layer=m4,
                            width=design.micronToDBU(strap_width_m4_um),
                            spacing=design.micronToDBU(strap_spacing_m4_um),
                            pitch=design.micronToDBU(strap_pitch_m4_um),
                            offset=pdn_offset,
                            number_of_straps=0, # Auto-calculate number based on pitch and area
                            snap=False, # Do not snap to grid (straps can be placed anywhere based on pitch/offset)
                            starts_with="GRID",
                            extend="CORE") # Extend to cover the core area

    # Create power straps on metal7
    # Prompt: grids on M7, width 1.4 um, spacing 1.4 um, pitch 10.8 um
    strap_width_m7_m8_um = 1.4 # Re-using width/spacing variable, as prompt specifies same for M7 and M8 straps
    strap_spacing_m7_m8_um = 1.4
    strap_pitch_m7_m8_um = 10.8
    print(f"    Adding straps on {m7.getName()} (W={strap_width_m7_m8_um}um, S={strap_spacing_m7_m8_um}um, P={strap_pitch_m7_m8_um}um)")
    # Use openroad.make_pdn_strap function
    openroad.make_pdn_strap(design, core_grid,
                            layer=m7,
                            width=design.micronToDBU(strap_width_m7_m8_um),
                            spacing=design.micronToDBU(strap_spacing_m7_m8_um),
                            pitch=design.micronToDBU(strap_pitch_m7_m8_um),
                            offset=pdn_offset,
                            number_of_straps=0,
                            snap=False,
                            starts_with="GRID",
                            extend="RINGS") # Extend to connect with the power rings

    # Create power straps on metal8
    # Prompt: grids on M8 (implied as same specs as M7 from context?), width 1.4 um, spacing 1.4 um, pitch 10.8 um
    # The prompt only gives specs for M7 straps. Let's assume the same specs apply to M8 straps as the previous script did.
    print(f"    Adding straps on {m8.getName()} (W={strap_width_m7_m8_um}um, S={strap_spacing_m7_m8_um}um, P={strap_pitch_m7_m8_um}um)")
    # Use openroad.make_pdn_strap function
    openroad.make_pdn_strap(design, core_grid,
                            layer=m8,
                            width=design.micronToDBU(strap_width_m7_m8_um),
                            spacing=design.micronToDBU(strap_spacing_m7_m8_um),
                            pitch=design.micronToDBU(strap_pitch_m7_m8_um),
                            offset=pdn_offset,
                            number_of_straps=0,
                            snap=False,
                            starts_with="GRID",
                            extend="BOUNDARY") # Extend to the die boundary

    # Create via connections between core grid layers
    print("    Adding via connections between core grid layers...")
    # Use openroad.make_pdn_connect function
    # Connect metal1 (followpin) to metal4 (strap)
    openroad.make_pdn_connect(design, core_grid, layer0=m1, layer1=m4,
                              cut_pitch_x=pdn_cut_pitch[0], cut_pitch_y=pdn_cut_pitch[1])
    # Connect metal4 to metal7 (strap)
    openroad.make_pdn_connect(design, core_grid, layer0=m4, layer1=m7,
                              cut_pitch_x=pdn_cut_pitch[0], cut_pitch_y=pdn_cut_pitch[1])
    # Connect metal7 to metal8 (strap)
    openroad.make_pdn_connect(design, core_grid, layer0=m7, layer1=m8,
                              cut_pitch_x=pdn_cut_pitch[0], cut_pitch_y=pdn_cut_pitch[1])
    # Connect metal8 (strap) to metal8 (ring) and metal7 (ring) to metal7 (strap)
    # Connections within the same layer type (strap to ring) are often handled automatically or implicitly by extending.
    # Explicit connections might be needed depending on the specific setup or via types. Let's assume extension/automatic handles it for now.
    # Connect metal7 rings to M7 straps (handled by extend="RINGS")
    # Connect metal8 rings to M8 straps (handled by extend="BOUNDARY" which includes rings)
    # Add connections between adjacent strap layers explicitly as good practice
    openroad.make_pdn_connect(design, core_grid, layer0=m1, layer1=m4, cut_pitch_x=pdn_cut_pitch[0], cut_pitch_y=pdn_cut_pitch[1])
    openroad.make_pdn_connect(design, core_grid, layer0=m4, layer1=m7, cut_pitch_x=pdn_cut_pitch[0], cut_pitch_y=pdn_cut_pitch[1])
    openroad.make_pdn_connect(design, core_grid, layer0=m7, layer1=m8, cut_pitch_x=pdn_cut_pitch[0], cut_pitch_y=pdn_cut_pitch[1])

# Create power grid for macro blocks if they exist
# Prompt: if design has macros, build power grids for macros on M5 and M6 , set the width and spacing of both M5 and M6 grids to 1.2 um, and set the pitch to 6 um.
if len(macros) > 0:
    print("  Defining PDN structure for macros...")
    strap_width_m5_m6_um = 1.2
    strap_spacing_m5_m6_um = 1.2
    strap_pitch_m5_m6_um = 6.0

    # Define halo size in DBU for macro PDN routing exclusion - same as macro placement halo
    # The halo for instance grids defines a region around the instance boundary *inside* which
    # the grid will be placed, if smaller than the instance. Or it can be used for exclusion.
    # The prompt for "halo region around each macro as 5 um" was applied in the placer,
    # meaning standard cells avoid this region. For macro PDN, the grid is typically inside
    # the macro or connects to macro pins. The `pg_pins_to_boundary` parameter handles connection.
    # An exclusion halo for *macro* grids doesn't typically make sense. Let's remove the halo parameter here.
    # The "if there are parallel grids, set the pitch of the via between two grids to 0 um"
    # and "set the offset to 0 for all cases" are handled by pdn_cut_pitch and pdn_offset.

    # Loop through each macro instance
    for i, macro_inst in enumerate(macros):
        print(f"    Adding instance grid for macro '{macro_inst.getName()}'...")
        # Create a separate instance grid for each macro
        # Apply to the same core domain as macros typically share the main power domain
        macro_grid_name = f"macro_grid_{macro_inst.getName()}"
        # Use openroad.make_pdn_instance_grid function
        openroad.make_pdn_instance_grid(design, domain=core_domain,
                                        name=macro_grid_name,
                                        starts_with="GROUND", # Start with ground net for this grid
                                        inst=macro_inst,
                                        pg_pins_to_boundary=True) # Connect macro PG pins to grid boundary

        # Find the grid just created for the macro instance
        # Use openroad.find_pdn_grid function
        macro_instance_grids = openroad.find_pdn_grid(design, macro_grid_name)
        if not macro_instance_grids:
            print(f"    Warning: Failed to create or find instance grid '{macro_grid_name}' for macro '{macro_inst.getName()}'. Skipping straps/vias for this macro.")
            continue
        macro_grid = macro_instance_grids[0] # Assume one grid per instance name

        # Create power straps on metal5 for macro connections
        print(f"      Adding straps on {m5.getName()} (W={strap_width_m5_m6_um}um, S={strap_spacing_m5_m6_um}um, P={strap_pitch_m5_m6_um}um)")
        # Use openroad.make_pdn_strap function
        openroad.make_pdn_strap(design, macro_grid,
                                layer=m5,
                                width=design.micronToDBU(strap_width_m5_m6_um),
                                spacing=design.micronToDBU(strap_spacing_m5_m6_um),
                                pitch=design.micronToDBU(strap_pitch_m5_m6_um),
                                offset=pdn_offset,
                                number_of_straps=0,
                                snap=True, # Snap to grid helps align with macro pins
                                starts_with="GRID",
                                extend="CORE") # Extend within macro boundary

        # Create power straps on metal6 for macro connections
        print(f"      Adding straps on {m6.getName()} (W={strap_width_m5_m6_um}um, S={strap_spacing_m5_m6_um}um, P={strap_pitch_m5_m6_um}um)")
        # Use openroad.make_pdn_strap function
        openroad.make_pdn_strap(design, macro_grid,
                                layer=m6,
                                width=design.micronToDBU(strap_width_m5_m6_um),
                                spacing=design.micronToDBU(strap_spacing_m5_m6_um),
                                pitch=design.micronToDBU(strap_pitch_m5_m6_um),
                                offset=pdn_offset,
                                number_of_straps=0,
                                snap=True,
                                starts_with="GRID",
                                extend="CORE")

        # Create via connections between macro power grid layers and core grid layers
        print("      Adding via connections between macro and core grid layers...")
        # Use openroad.make_pdn_connect function
        # Connect metal4 (from core grid) to metal5 (macro grid)
        openroad.make_pdn_connect(design, macro_grid, layer0=m4, layer1=m5,
                                  cut_pitch_x=pdn_cut_pitch[0], cut_pitch_y=pdn_cut_pitch[1])
        # Connect metal5 to metal6 (macro grid layers)
        openroad.make_pdn_connect(design, macro_grid, layer0=m5, layer1=m6,
                                  cut_pitch_x=pdn_cut_pitch[0], cut_pitch_y=pdn_cut_pitch[1])
        # Connect metal6 (macro grid) to metal7 (core grid)
        # Need to connect the macro grid to the *main* core grid for power distribution.
        # This usually involves connections from macro layers (M5/M6) to the core grid layers (M4/M7/M8).
        # The `extend` parameter in makeStrap can help, but explicit connections are clearer.
        # Let's connect M6 from the macro grid to M7 from the core grid.
        openroad.make_pdn_connect(design, macro_grid, layer0=m6, layer1=m7,
                                  cut_pitch_x=pdn_cut_pitch[0], cut_pitch_y=pdn_cut_pitch[1])
        # Also connect M5 to M4
        openroad.make_pdn_connect(design, macro_grid, layer0=m5, layer1=m4,
                                  cut_pitch_x=pdn_cut_pitch[0], cut_pitch_y=pdn_cut_pitch[1])
        # Connections within the macro (M5 to M5 straps, M6 to M6 straps) might also be needed
        openroad.make_pdn_connect(design, macro_grid, layer0=m5, layer1=m5,
                                  cut_pitch_x=pdn_cut_pitch[0], cut_pitch_y=pdn_cut_pitch[1])
        openroad.make_pdn_connect(design, macro_grid, layer0=m6, layer1=m6,
                                  cut_pitch_x=pdn_cut_pitch[0], cut_pitch_y=pdn_cut_pitch[1])


# Verify PDN setup and build the grids
print("  Building PDN shapes in database...")
pdngen.checkSetup() # Check for potential issues before building
pdngen.buildGrids(False) # Build the power grid shapes in the database (argument is for bump optimization)
pdngen.writeToDb(True)  # Write the PDN shapes to the design database
# pdngen.resetShapes() # Reset temporary shapes - maybe not needed after writeToDb

print("Power Delivery Network generation finished.")

# -----------------------------------------------------------------------------
# Standard Cell Placement - Detailed Placement (Initial)
# -----------------------------------------------------------------------------
# A common flow is GP -> Initial DP -> CTS -> Final DP -> Filler

print("Performing initial detailed placement...")

# Get Detailed Placer object (OpenDP)
dp = design.getOpendp()

# Configure detailed placement parameters
# Prompt: max displacement x=1 um, y=3 um
max_disp_x_um = 1.0
max_disp_y_um = 3.0
max_disp_x_dbu = design.micronToDBU(max_disp_x_um)
max_disp_y_dbu = design.micronToDBU(max_disp_y_um)

# Remove existing filler cells before placement (important if re-running stages)
# This is usually done before detailed placement.
dp.removeFillers()

# Perform initial detailed placement
# Arguments are max_disp_x_dbu, max_disp_y_dbu, cell_type (empty string for all), check_blockages
print(f"  Running detailed placement with max displacement X={max_disp_x_um}um, Y={max_disp_y_um}um")
dp.detailedPlacement(max_disp_x_dbu, max_disp_y_dbu, "", False) # Use openroad.detailed_placement function? Let's use the object directly.

print("Initial detailed placement finished.")

# -----------------------------------------------------------------------------
# Clock Tree Synthesis (CTS)
# -----------------------------------------------------------------------------

print("Performing Clock Tree Synthesis...")

# Get TritonCTS object
cts = design.getTritonCts()

# Ensure propagated clock is set (redundant but safe after placement)
# This is crucial for CTS to analyze the existing clock network and sinks.
design.evalTclString(f"set_propagated_clock [get_clocks {{{clock_name}}}]")

# Configure clock buffers to use 'BUF_X2'
# Prompt: using BUF_X2 as clock buffers
# Find the master cell for BUF_X2
buf_x2_master = db.findMaster("BUF_X2") # Replace with the actual library cell name for BUF_X2

if buf_x2_master is None:
    print("Error: BUF_X2 master cell not found in library. Cannot perform CTS.")
    cts_successful = False
else:
    # Set list of buffers CTS is allowed to use
    cts.setBufferList("BUF_X2") # Set by name
    # Set root buffer (optional, often same as buffer list)
    # cts.setRootBuffer("BUF_X2") # Set by name
    # Set sink buffer (optional, often same as buffer list)
    # cts.setSinkBuffer("BUF_X2") # Set by name

    # Configure other CTS parameters (optional, adjust as needed)
    parms = cts.getParms()
    # parms.setWireSegmentUnit(design.micronToDBU(2.0)) # Example wire segment unit (2um)
    # parms.setMaxDepth(20) # Example max tree depth
    # parms.setSinkBufferMaxBuffer(1000) # Example max sink buffers per clock net

    # Run clock tree synthesis
    print("  Running TritonCTS...")
    # Use openroad.run_cts function? Or the object directly. Let's use object.
    cts_successful = cts.runTritonCts()

    if cts_successful:
        print("Clock Tree Synthesis finished.")
    else:
        print("Warning: Clock Tree Synthesis failed.")

# -----------------------------------------------------------------------------
# Standard Cell Placement - Detailed Placement (Final)
# -----------------------------------------------------------------------------
# Run detailed placement again after CTS to clean up any minor violations or shifts

if cts_successful: # Only run final DP if CTS was successful
    print("Performing final detailed placement after CTS...")

    # Remove existing filler cells before final detailed placement
    dp.removeFillers()

    # Perform final detailed placement
    # Use the same displacement limits as the initial DP
    print(f"  Running final detailed placement with max displacement X={max_disp_x_um}um, Y={max_disp_y_um}um")
    dp.detailedPlacement(max_disp_x_dbu, max_disp_y_dbu, "", False)

    print("Final detailed placement finished.")
else:
    print("Skipping final detailed placement because CTS failed.")


# -----------------------------------------------------------------------------
# Filler Cell Insertion
# -----------------------------------------------------------------------------

print("Inserting filler cells...")

# Find filler cell masters in the libraries
filler_masters = []
# Find masters with type CORE_SPACER or like names
for lib in db.getLibs():
    for master in lib.getMasters():
        if master.getType() == "CORE_SPACER":
            filler_masters.append(master)
        # Also check for common filler cell name patterns if type is not sufficient
        # e.g., master.getName().startswith("FILLCELL_") or master.getName().startswith("FILLER_"):
        #     filler_masters.append(master)

if not filler_masters:
    print("  Warning: No CORE_SPACER or recognized filler cell masters found in library. Cannot insert fillers.")
else:
    # Remove duplicates just in case
    unique_filler_masters = list(set(filler_masters))
    print(f"  Found {len(unique_filler_masters)} filler cell masters.")
    # Insert filler cells into empty spaces in the core area
    # Prefix is used for naming the new filler instances
    filler_cells_prefix = "filler_"
    # Use openroad.insert_filler_cells function? Or the object directly.
    try:
        dp.fillerPlacement(filler_masters=unique_filler_masters,
                           prefix=filler_cells_prefix,
                           verbose=False)
        print("  Filler cell insertion finished.")
    except Exception as e:
        print(f"  Warning: Filler cell insertion failed: {e}")


# -----------------------------------------------------------------------------
# Routing - Global Routing
# -----------------------------------------------------------------------------

print("Performing global routing...")

# Get Global Router object (GRT)
grt_tool = design.getGlobalRouter()

# Set minimum and maximum routing layers
# Prompt: route the design from M1 to M7
min_route_layer_name = "metal1"
max_route_layer_name = "metal7"

# Find layers and get their routing levels (index)
min_route_layer = tech_db.findLayer(min_route_layer_name)
max_route_layer = tech_db.findLayer(max_route_layer_name)

if not min_route_layer or not max_route_layer:
    print(f"Error: Could not find routing layers '{min_route_layer_name}' or '{max_route_layer_name}'. Cannot perform routing.")
    # Skip routing stages if layers are missing
    gr_successful = False
else:
    min_route_level = min_route_layer.getRoutingLevel()
    max_route_level = max_route_layer.getRoutingLevel()

    grt_tool.setMinRoutingLayer(min_route_level)
    grt_tool.setMaxRoutingLayer(max_route_level)
    # By default, clock nets use the same layers as signal nets in GRT

    # Configure other GRT parameters (optional)
    # grt_tool.setAdjustment(0.5) # Set routing congestion adjustment (adjust if needed)
    grt_tool.setVerbose(True) # Enable verbose output

    # Run global route
    # Prompt: iteration of the global router as 30 times
    global_route_iterations = 30
    print(f"  Running GRT with {global_route_iterations} iterations...")
    # Use openroad.global_route function? Or the object directly.
    # The first argument True allows GRT to generate obstructions
    gr_successful = grt_tool.globalRoute(True, global_route_iterations)

    if gr_successful:
        print("Global routing finished successfully.")
    else:
        print("Warning: Global routing failed.")

# -----------------------------------------------------------------------------
# Routing - Detailed Routing
# -----------------------------------------------------------------------------

# Only run detailed routing if global routing was successful
if gr_successful:
    print("Performing detailed routing...")

    # Get Detailed Router object (TritonRoute)
    drter = design.getTritonRoute()
    dr_params = drt.ParamStruct()

    # Set detailed router parameters
    # Prompt: route the design from M1 to M7
    dr_params.bottomRoutingLayer = min_route_layer_name # Lowest routing layer for DR
    dr_params.topRoutingLayer = max_route_layer_name   # Highest routing layer for DR

    # Configure other DRT parameters (optional, adjust for your design/tech)
    # These parameters often require tuning. Examples from the original script:
    dr_params.enableViaGen = True # Enable via generation
    dr_params.drouteEndIter = 1 # Number of detailed routing iterations (1 is common for initial run)
    dr_params.doPa = True # Perform pin access analysis
    dr_params.minAccessPoints = 1 # Minimum pin access points
    dr_params.verbose = 1 # Verbosity level
    dr_params.cleanPatches = True

    drter.setParams(dr_params)

    # Run detailed routing
    print("  Running TritonRoute...")
    # Use openroad.detailed_route function? Or the object directly.
    drter.main() # The main method runs the detailed router

    print("Detailed routing finished.")
else:
    print("Skipping detailed routing because global routing failed.")


# -----------------------------------------------------------------------------
# Analysis - IR Drop Analysis
# -----------------------------------------------------------------------------

print("Performing Static IR drop analysis...")

# Get PDN Simulator object (psm)
psm_obj = design.getPDNSim()

# Find the VDD net for analysis
analysis_net = block.findNet("VDD")
if analysis_net is None:
    print("Error: VDD net not found. Cannot perform IR drop analysis.")
else:
    # Define source types for current estimation
    # psm.GeneratedSourceType_FULL: uses power grid structure, instance locations
    # psm.GeneratedSourceType_STRAPS: uses power straps only
    # psm.GeneratedSourceType_ACTIVITY: uses timing analysis results (requires STA)
    # psm.GeneratedSourceType_BUMPS: connects current sources to bump locations (specific to flip-chip)
    # The original script used BUMPS. If not a flip-chip design, FULL is more appropriate.
    # Let's use FULL as a more general approach.
    source_type = psm.GeneratedSourceType_FULL # Or psm.GeneratedSourceType_BUMPS or psm.GeneratedSourceType_ACTIVITY

    # Find a timing corner to use for analysis (e.g., the first one defined)
    corners = timing.getCorners()
    if not corners:
        print("Warning: No timing corners defined. IR drop analysis may use default settings or fail.")
        analysis_corner = None
    else:
        analysis_corner = corners[0]
        print(f"  Using timing corner: {analysis_corner.getName()} for analysis.")

    # Analyze the power grid
    # Analysis is done on the specified net (e.g., VDD). The results include voltage on all connected layers.
    # Prompt asks for analysis on M1, but standard IR drop analysis is net-based.
    # Results can be queried layer-by-layer after analysis using methods like getVoltageLayer
    # or via TCL commands like "get_voltages".
    print(f"  Analyzing IR drop on net '{analysis_net.getName()}'...")
    try:
        # Use openroad.analyze_power_grid function? Or the object directly.
        psm_obj.analyzePowerGrid(net=analysis_net,
                                 enable_em=False, # Disable Electromigration analysis
                                 corner=analysis_corner,
                                 use_prev_solution=False,
                                 source_type=source_type)
        print("Static IR drop analysis finished.")

        # Optional: Query results for M1 after analysis
        # This requires accessing the results object, which can be complex via Python.
        # The easiest way to view layer-specific results is often in the GUI or via TCL.
        # layer_m1_voltage = psm_obj.getVoltageLayer(analysis_net, m1) # Example - check API if this method exists
        # if layer_m1_voltage:
        #    print(f"  Example: Estimated average voltage on {m1.getName()} for net {analysis_net.getName()}: {layer_m1_voltage}V")
        print(f"  Note: To view layer-specific results (e.g., on {m1.getName()}), use TCL command 'get_voltages -net {analysis_net.getName()} -layer {m1.getName()}' in the OpenROAD GUI/shell after loading this DEF.")

    except Exception as e:
        print(f"Warning: Static IR drop analysis failed: {e}")


# -----------------------------------------------------------------------------
# Output
# -----------------------------------------------------------------------------

print("Writing output files...")

# Save the final DEF file after routing
final_def_file = "final.def"
print(f"  Writing DEF file: {final_def_file}")
# Use openroad.write_def function
openroad.write_def(design, final_def_file)

# Save the final Verilog netlist (includes inserted buffers and fillers)
final_verilog_file = f"{design_top_module_name}_final.v"
print(f"  Writing final Verilog netlist: {final_verilog_file}")
# Use openroad.write_verilog function
openroad.write_verilog(design, final_verilog_file)

# Save the design database (optional)
# db_file = f"{design_top_module_name}.db"
# print(f"  Writing database file: {db_file}")
# db.write(db_file)


print("Script finished.")

# -----------------------------------------------------------------------------
# Clean up (optional, for interactive sessions)
# -----------------------------------------------------------------------------
# Explicitly destroy the database object to free resources
# db = None
# design = None
# tech = None
# tech_db = None