import odb
import openroad as ord
import sys # Import sys to gracefully exit on errors

# Get the OpenROAD design object
design = ord.get_design()

# --- 1. Read Input Files ---
# Assuming files are available in the current directory or specified paths
# Replace these with your actual file paths
tech_file = "tech.tf"
lef_files = ["tech_lef.lef", "library_macros.lef", "std_cell.lef"] # Add all necessary LEF files, including standard cells
lib_files = ["library.lib"] # Add all necessary Liberty files
# The gate-level netlist is typically in Verilog format before placement
netlist_verilog = "netlist.v" # Assuming input netlist is Verilog
top_module_name = "top" # Replace with your actual top module name
output_def_file_placement = "placement.def" # Name specified in the prompt for post-placement DEF

# Read the technology file using evalTclString as per verification feedback
try:
    # Standard way to read .tf file is via the Tcl command
    design.evalTclString(f"read_tech {tech_file}")
    print(f"Read tech file using evalTclString: {tech_file}")
except Exception as e:
    print(f"Error executing 'read_tech {tech_file}' via evalTclString: {e}")
    sys.exit(1)

# Read LEF files
for lef in lef_files:
    try:
        design.readLef(lef)
        print(f"Read LEF file: {lef}")
    except Exception as e:
        print(f"Error reading LEF file {lef}: {e}")
        # Decide if you want to exit or continue if a LEF is missing
        # For critical LEFs, exiting is appropriate
        sys.exit(1)


# Read Liberty files
for lib in lib_files:
    try:
        design.readLiberty(lib)
        print(f"Read Liberty file: {lib}")
    except Exception as e:
        print(f"Error reading Liberty file {lib}: {e}")
        # Decide if you want to exit or continue
        sys.exit(1)


# Read the gate-level netlist (Verilog) and link
try:
    design.readVerilog(netlist_verilog)
    print(f"Read netlist Verilog: {netlist_verilog}")
except Exception as e:
    print(f"Error reading Verilog file {netlist_verilog}: {e}")
    sys.exit(1)

try:
    design.link(top_module_name)
    print(f"Linked design with top module: {top_module_name}")
except Exception as e:
    print(f"Error linking design (check Verilog and Liberty files, top module name): {e}")
    sys.exit(1)

# Get the core block after linking
block = design.getBlock()
if not block:
    print("Error: Block not found after linking. Ensure linking was successful.")
    sys.exit(1)

# --- 2. Define Clock ---
# Define the clock signal on the specified port
clock_port = "clk_i"
clock_period_ns = 50.0 # 50 ns
# Convert to picoseconds for create_clock (create_clock expects integer picoseconds)
clock_period_ps = int(clock_period_ns * 1000)
clock_name = "core_clock"

# Use evalTclString as the create_clock command is typically run via Tcl
# It's good practice to check if the port exists first
port = block.findBTerm(clock_port)
if not port:
     print(f"Error: Clock port '{clock_port}' not found in the design. Check netlist.")
     sys.exit(1)

try:
    design.evalTclString(f"create_clock -period {clock_period_ps} [get_ports {clock_port}] -name {clock_name}")
    print(f"Defined clock '{clock_name}' on port '{clock_port}' with period {clock_period_ns} ns")
except Exception as e:
    print(f"Error creating clock: {e}")
    sys.exit(1)


# Optional: Set RC values for clock and signal nets (good practice, though not explicitly requested)
# These values depend on your technology node and layer usage and are often in the tech file
# If not, you might need to set them via Tcl:
# try:
#     design.evalTclString("set_wire_rc -clock -resistance 0.03574 -capacitance 0.07516")
#     design.evalTclString("set_wire_rc -signal -resistance 0.03574 -capacitance 0.07516")
#     print("Set wire RC values.")
# except Exception as e:
#     print(f"Warning: Could not set wire RC values (commands might not be available or values invalid): {e}")


# --- 3. Floorplanning ---
print("Starting floorplanning...")
floorplan = design.getFloorplan()

# Find a valid site from the block or technology
site = None
# Prefer finding site from rows if they exist (means site is used in definition)
if block.getRows():
    row = block.getRows()[0]
    if row:
        site = row.getSite()
        if site:
             print(f"Using site from existing rows: {site.getName()}")
else:
    # If no rows, try finding a common site name from tech
    tech = design.getTech().getDB().getTech()
    if tech:
        # Common site names: "core", "unit", "default", check your LEF/Tech
        common_site_names = ["core", "unit", "default"] # Add site names from your LEF here
        for name in common_site_names:
            found_site = tech.findSite(name)
            if found_site:
                site = found_site
                print(f"Could not find site from rows, found site by name: {site.getName()}")
                break

if not site:
     print("Error: Site could not be determined for floorplanning. Ensure LEF/Tech define sites and check site names.")
     sys.exit(1)

# Set floorplan parameters
target_utilization = 0.35  # Target utilization set to 35%
aspect_ratio = 1.0         # Aspect ratio is not specified, using 1.0 (square)
margin_microns = 10        # Core-to-die spacing in microns

# Convert margin to DBU
dbu_per_micron = design.getTech().getDB().getTech().getDbUnitsPerMicron()
margin_dbu = int(margin_microns * dbu_per_micron) # Ensure integer DBU
print(f"Core-to-die spacing: {margin_microns} microns ({margin_dbu} DBU)")

# Initialize floorplan using utilization and margins
# initFloorplan(utilization, aspect_ratio, bottom_space, top_space, left_space, right_space, site)
try:
    # The initFloorplan method takes DBU for margins
    floorplan.initFloorplan(target_utilization, aspect_ratio, margin_dbu, margin_dbu, margin_dbu, margin_dbu, site)
    print("Floorplan initialized.")
except Exception as e:
    print(f"Error initializing floorplan: {e}")
    sys.exit(1)

# Create placement tracks based on the site definition and floorplan grid
# This is essential for standard cell placement
try:
    floorplan.makeTracks()
    print("Placement tracks created.")
except Exception as e:
    print(f"Error creating placement tracks: {e}")
    # Depending on error, you might exit or continue with a warning
    # For tracks, it's often critical, so exiting is safer
    sys.exit(1)


# --- 4. I/O Pin Placement ---
print("Starting I/O pin placement...")
io_placer = design.getIOPlacer()
io_placer_params = io_placer.getParameters()

# Set metal layers for I/O pin placement as M8 (horizontal) and M9 (vertical)
# Layers are found by name from the technology database
tech = design.getTech().getDB().getTech()
metal8_layer = tech.findLayer("metal8")
metal9_layer = tech.findLayer("metal9")

if not metal8_layer or not metal9_layer:
    print("Error: Could not find metal8 or metal9 layers for pin placement. Ensure LEF/Tech define these layers. Aborting.")
    sys.exit(1)

# Clear existing layers and add specified ones
io_placer.clearHorLayers()
io_placer.clearVerLayers()
io_placer.addHorLayer(metal8_layer)
io_placer.addVerLayer(metal9_layer)
print(f"Set I/O pin layers: Horizontal on {metal8_layer.getName()}, Vertical on {metal9_layer.getName()}")

# Configure IO placer parameters (using some defaults or reasonable values)
io_placer_params.setRandSeed(42) # Optional: Set seed for repeatability
# setMinDistanceInTracks(False) means distance is in DBU, not site tracks
io_placer_params.setMinDistanceInTracks(False)
io_placer_params.setMinDistance(design.micronToDBU(0)) # Minimum distance between pins (0 is common)
io_placer_params.setCornerAvoidance(design.micronToDBU(0)) # Corner avoidance distance (0 is common)
# Note: Parameters like side selection (left/right/top/bottom) can also be configured

# Run I/O pin placement (using annealing mode as in draft, random mode True)
# The random_mode parameter in runAnnealing enables randomization within the annealing process
io_placer_random_mode = True
try:
    io_placer.runAnnealing(io_placer_random_mode)
    print("I/O pin placement completed.")
except Exception as e:
    print(f"Error during I/O pin placement: {e}")
    sys.exit(1)


# --- 5. Macro Placement ---
print("Starting macro placement...")
# Identify macro instances (instances whose master is a block, not a standard cell)
# After linking, instances that are not standard cells are generally considered macros or blocks
macros = [inst for inst in block.getInsts() if not inst.getMaster().isStdCell()]

if len(macros) > 0:
    mpl = design.getMacroPlacer()

    # Get the core area rectangle - macros are typically placed within this fence
    # Ensure the core area is valid after floorplanning
    core = block.getCoreArea()
    if core.isNull():
        print("Error: Core area is null after floorplanning. Cannot place macros.")
        sys.exit(1)

    # Define halo region around macros in microns
    macro_halo_microns = 5.0
    print(f"Setting macro halo to {macro_halo_microns} microns.")

    # Run macro placement using the placer, specifying the halo and fence.
    # The request for "5 um spacing between each other" is complex to guarantee
    # purely through simple parameters. Halo primarily keeps standard cells/routing away.
    # The placer algorithm itself handles macro-to-macro spacing constraints if supported
    # and configured, but a simple API call might not expose fine-grained control.
    # We use the place method with halo and fence defined by the core area.
    try:
        mpl.place(
            # Parameters passed to the place method are usually in microns
            halo_width = macro_halo_microns,
            halo_height = macro_halo_microns,
            # Set the fence region to the core area (converted from DBU to microns)
            fence_lx = design.dbuToMicrons(core.xMin()),
            fence_ly = design.dbuToMicrons(core.yMin()),
            fence_ux = design.dbuToMicrons(core.xMax()),
            fence_uy = design.dbuToMicrons(core.yMax()),
            # Additional parameters can be tuned; using sensible defaults or examples
            # Many parameters from the draft are internal tuning knobs for the algorithm
            # Passing a subset is common, let the placer handle defaults for others
            num_threads = 64, # Example thread count
            max_num_macro = len(macros), # Try to place all identified macros
            # target_util and other partition-related params are less critical for
            # the final placment call if the fence is defined by the core area.
            # Omitting some less relevant params for clarity unless they are critical
            # based on placer documentation.
        )
        print("Macro placement completed.")
    except Exception as e:
        print(f"Error during macro placement: {e}")
        # Macro placement errors can be critical
        sys.exit(1)
else:
    print("No macros found. Skipping macro placement.")


# --- 6. Standard Cell Placement (Global Placement) ---
print("Starting global placement...")
gpl = design.getReplace()

# Configure global placement parameters
# Timing driven typically requires spef/sdf and timing setup
# Routability driven helps spread cells to avoid routing congestion hotspots
gpl.setTimingDrivenMode(False)      # Timing driven disabled as per prompt's lack of timing constraints
gpl.setRoutabilityDrivenMode(True) # Routability driven enabled (common practice)
gpl.setUniformTargetDensityMode(True) # Uniform density target

try:
    # Perform initial placement (fast phase)
    gpl.doInitialPlace(threads = 4) # Use example thread count

    # Perform Nesterov placement (detailed global placement phase of GPL)
    gpl.doNesterovPlace(threads = 4) # Use example thread count
    print("Global placement completed.")
except Exception as e:
    print(f"Error during global placement: {e}")
    sys.exit(1)


# --- 7. Standard Cell Placement (Detailed Placement) ---
print("Starting detailed placement...")
dp = design.getOpendp()

# Set maximum displacement in x and y directions to 0 microns as requested
max_disp_x_microns = 0.0
max_disp_y_microns = 0.0

# Convert micron values to DBU (Database Units)
# OpenDB methods often expect DBU
max_disp_x_dbu = design.micronToDBU(max_disp_x_microns)
max_disp_y_dbu = design.micronToDBU(max_disp_y_microns)
print(f"Detailed placement max displacement set to ({max_disp_x_microns}, {max_disp_y_microns}) microns.")

try:
    # Perform detailed placement with specified max displacements
    # detailedPlacement(max_displacement_x_dbu, max_displacement_y_dbu, cell_list, verbose)
    # An empty string for cell_list means all movable cells
    dp.detailedPlacement(max_disp_x_dbu, max_disp_y_dbu, "", False) # False for non-verbose output
    print("Detailed placement completed.")
except Exception as e:
    print(f"Error during detailed placement: {e}")
    sys.exit(1)


# --- 8. Dump Output DEF after Placement ---
# Dump the DEF file after the placement stage as requested by the prompt.
try:
    design.writeDef(output_def_file_placement)
    print(f"Wrote output DEF file after placement: {output_def_file_placement}")
except Exception as e:
    print(f"Error writing DEF file {output_def_file_placement}: {e}")
    # This error might not be critical enough to stop, but useful to report
    # Decide based on flow requirements. For this example, let's print warning.
    print("Warning: Failed to write placement DEF.")


# --- 9. Propagate Clock ---
# Propagate the clock signal after placement to update clock tree information
# This step is important for timing analysis and subsequent routing.
# This uses the placement results to calculate actual clock net delays.
try:
    # Using evalTclString for set_propagated_clock as it's a common Tcl command
    design.evalTclString(f"set_propagated_clock [get_clocks {{{clock_name}}}]")
    print(f"Propagated clock '{clock_name}'.")
except Exception as e:
    print(f"Warning: Could not propagate clock '{clock_name}' (command might fail if clock wasn't created or port not found): {e}")
    # This might be a warning or error depending on whether STA/CTS follows


# --- 10. Global Routing ---
print("Starting global routing...")
grt = design.getGlobalRouter()

# Set the number of global routing iterations (as requested, 20 times)
# The global_route command in Tcl typically takes an -iterations argument
# Using evalTclString is the standard way to pass specific arguments like this
num_gr_iterations = 20
print(f"Running global routing for {num_gr_iterations} iterations.")

try:
    # Run global routing using the Tcl command interface
    # This command requires valid technology setup (layers, vias, rules) from LEF/Tech
    design.evalTclString(f"global_route -iterations {num_gr_iterations}")
    print("Global routing completed.")
except Exception as e:
    print(f"Error during global routing: {e}")
    # Global routing errors are typically fatal for subsequent steps like detailed routing/DRC
    sys.exit(1)

# Optional: Dump DEF after routing if needed for visualization/debug (not requested by prompt)
# output_def_file_routed = "routed.def"
# try:
#     design.writeDef(output_def_file_routed)
#     print(f"Wrote output DEF file after routing: {output_def_file_routed}")
# except Exception as e:
#     print(f"Warning: Failed to write routed DEF: {e}")


print("Script finished.")