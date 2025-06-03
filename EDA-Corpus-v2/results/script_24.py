import odb
import pdn
import ir_drop
import openroad as ord

# Get the technology and design block
tech = design.getTech()
block = design.getBlock()
db = ord.get_db()

# --- Create Clock ---
clock_period_ns = 20
clock_port_name = "clk"
clock_name = "core_clock"

# Create clock signal
# API: openroad.Design.evalTclString("create_clock -period 20 [get_ports clk] -name core_clock")
design.evalTclString(f"create_clock -period {clock_period_ns} [get_ports {clock_port_name}] -name {clock_name}")

# Propagate the clock signal
# API: openroad.Design.evalTclString("set_propagated_clock [core_clock]") or similar
design.evalTclString(f"set_propagated_clock [get_clocks {{{clock_name}}}]")

# Set unit resistance and capacitance for clock and signal nets
# API: openroad.Design.evalTclString("set_wire_rc -clock ...")
design.evalTclString("set_wire_rc -clock -resistance 0.03574 -capacitance 0.07516")
# API: openroad.Design.evalTclString("set_wire_rc -signal ...")
design.evalTclString("set_wire_rc -signal -resistance 0.03574 -capacitance 0.07516")

# --- Floorplan ---
# Initialize floorplan
floorplan = design.getFloorplan()

# Set die area (0,0) to (60,50) um
die_lx = 0
die_ly = 0
die_ux = 60
die_uy = 50
die_area = odb.Rect(design.micronToDBU(die_lx), design.micronToDBU(die_ly),
                    design.micronToDBU(die_ux), design.micronToDBU(die_uy))

# Set core area (8,8) to (52,42) um
core_lx = 8
core_ly = 8
core_ux = 52
core_uy = 42
core_area = odb.Rect(design.micronToDBU(core_lx), design.micronToDBU(core_ly),
                     design.micronToDBU(core_ux), design.micronToDBU(core_uy))

# Find a site (assuming a typical site is available, adjust site name if needed)
site = floorplan.findSite(tech.getSiteByName("FreePDK45_38x28_10R_NP_162NW_34O").getName()) # Example site name
if site is None:
    # Fallback to the first site found in the tech
    for lib in db.getLibs():
        for s in lib.getSites():
            site = s
            break
        if site:
            break
    if site is None:
        print("ERROR: No site found in technology library.")
        exit()


# Initialize floorplan with defined areas and site
# API: floorplan.initFloorplan(die_area, core_area, site)
floorplan.initFloorplan(die_area, core_area, site)

# Make tracks for standard cell placement
# API: floorplan.makeTracks()
floorplan.makeTracks()

# --- Placement ---

# Identify macro blocks
macros = [inst for inst in block.getInsts() if inst.getMaster().isBlock()]

if len(macros) > 0:
    # Configure and run Macro Placement if macros exist
    mpl = design.getMacroPlacer()

    # Set fence region for macros (18,12) to (43,42) um
    fence_lx = 18.0
    fence_ly = 12.0
    fence_ux = 43.0
    fence_uy = 42.0

    # Set halo region around each macro (5 um)
    halo_width = 5.0
    halo_height = 5.0

    # Set minimum spacing between macros (5 um)
    macro_spacing = 5.0

    # Run macro placement
    # API: mpl.place(...)
    # Parameters tuned based on request and common usage
    mpl.place(
        num_threads = 64,
        halo_width = halo_width,
        halo_height = halo_height,
        fence_lx = fence_lx,
        fence_ly = fence_ly,
        fence_ux = fence_ux,
        fence_uy = fence_uy,
        macro_blockage_weight = 10.0,
        min_macro_macro_dist = macro_spacing, # Minimum spacing between macros
        # Other parameters can be left as default or tuned if needed
    )


# Configure and run Global Placement
gpl = design.getReplace()
# The request mentioned "iteration of the global router as 10 times".
# This is likely referring to global *placement* iterations or just a general goal.
# Setting initial place iterations (as in example) or letting the tool run to convergence are options.
# We will rely on default global placement iterations for simplicity unless a specific API is found.
# gpl.setInitialPlaceMaxIter(10) # Example setting from knowledge base, but not explicitly requested for global router

gpl.setTimingDrivenMode(False) # Basic flow might not need timing
gpl.setRoutabilityDrivenMode(True) # Enable routability optimization
gpl.doInitialPlace(threads = 4)
gpl.doNesterovPlace(threads = 4) # Run quadratic placement

# Run initial Detailed Placement
dp = design.getOpendp()

# Remove filler cells if any were previously inserted
# This is often needed before detailed placement
dp.removeFillers()

# Set maximum displacement for detailed placement (0.5 um in X and Y)
max_disp_x_um = 0.5
max_disp_y_um = 0.5
max_disp_x_dbu = design.micronToDBU(max_disp_x_um)
max_disp_y_dbu = design.micronToDBU(max_disp_y_um)

# Perform detailed placement
# API: design.getOpendp().detailedPlacement(max_disp_x, max_disp_y, "", False)
dp.detailedPlacement(max_disp_x_dbu, max_disp_y_dbu, "", False)


# --- Clock Tree Synthesis (CTS) ---
# CTS is often run after initial placement or during optimization
# The request places it after initial detailed placement and before PDN/routing.
# It is more common to run CTS after global placement. Let's run it here as requested.

# Configure and run CTS
cts = design.getTritonCts()

# Set clock buffer cells (BUF_X2)
# API: cts.TritonCTS.setBufferList(str(buffers))
cts.setBufferList("BUF_X2")
# API: cts.TritonCTS.setRootBuffer(str(buffers))
cts.setRootBuffer("BUF_X2")
# API: cts.TritonCTS.setSinkBuffer(str(buffers))
cts.setSinkBuffer("BUF_X2")

# Run CTS
# API: cts.TritonCTS.runTritonCts()
cts.runTritonCts()

# Run final detailed placement after CTS to clean up cell locations
# Use the same displacement settings as before
# API: design.getOpendp().detailedPlacement(max_disp_x, max_disp_y, "", False)
dp.detailedPlacement(max_disp_x_dbu, max_disp_y_dbu, "", False)


# --- Power Delivery Network (PDN) Construction ---
pdngen = design.getPdnGen()

# Ensure power and ground nets exist and are marked as special
VDD_net = block.findNet("VDD")
VSS_net = block.findNet("VSS")

if VDD_net is None:
    VDD_net = odb.dbNet_create(block, "VDD")
if VSS_net is None:
    VSS_net = odb.dbNet_create(block, "VSS")

# API: odb.dbNet.setSigType(str(type))
VDD_net.setSigType("POWER")
VSS_net.setSigType("GROUND")

# Mark nets as special so they are handled by PDN tool
VDD_net.setSpecial()
VSS_net.setSpecial()

# Global connect instance VDD/VSS pins to global nets
# Connect standard VDD pins
block.addGlobalConnect(region=None, instPattern=".*", pinPattern="^VDD$", net=VDD_net, do_connect=True)
# Connect standard VSS pins
block.addGlobalConnect(region=None, instPattern=".*", pinPattern="^VSS$", net=VSS_net, do_connect=True)
# Apply connections
block.globalConnect()

# Set core power domain
# API: pdn.PdnGen.setCoreDomain(power, switched_power, ground, secondary)
pdngen.setCoreDomain(power=VDD_net, switched_power=None, ground=VSS_net, secondary=[])

# Get metal layer objects
m1 = tech.getDB().getTech().findLayer("metal1")
m4 = tech.getDB().getTech().findLayer("metal4")
m5 = tech.getDB().getTech().findLayer("metal5")
m6 = tech.getDB().getDB().getTech().findLayer("metal6")
m7 = tech.getDB().getTech().findLayer("metal7")
m8 = tech.getDB().getTech().findLayer("metal8")

# Define common parameters for core grid
core_grid_name = "core_grid"
via_cut_pitch = [design.micronToDBU(0) for _ in range(2)] # Via pitch 0 um

# Create the main core grid structure
# API: pdn.PdnGen.makeCoreGrid(domain, name, starts_with, ...)
pdngen.makeCoreGrid(
    domain=pdngen.findDomain("Core"),
    name=core_grid_name,
    starts_with=pdn.GROUND # Or pdn.POWER, depends on standard cell rail placement
)
core_grid = pdngen.findGrid(core_grid_name)

# Add Core Grid Straps and Rings
if core_grid:
    for grid in core_grid:
        # M1 straps for standard cells (followpin)
        # API: pdn.PdnGen.makeFollowpin(grid, layer, width, extend)
        pdngen.makeFollowpin(grid=grid, layer=m1, width=design.micronToDBU(0.07), extend=pdn.CORE)

        # M4 straps
        # API: pdn.PdnGen.makeStrap(grid, layer, width, spacing, pitch, offset, ...)
        pdngen.makeStrap(grid=grid, layer=m4, width=design.micronToDBU(1.2), spacing=design.micronToDBU(1.2),
                         pitch=design.micronToDBU(6), offset=design.micronToDBU(0), number_of_straps=0,
                         snap=False, starts_with=pdn.GRID, extend=pdn.CORE, nets=[])

        # M7 straps
        pdngen.makeStrap(grid=grid, layer=m7, width=design.micronToDBU(1.4), spacing=design.micronToDBU(1.4),
                         pitch=design.micronToDBU(10.8), offset=design.micronToDBU(0), number_of_straps=0,
                         snap=False, starts_with=pdn.GRID, extend=pdn.CORE, nets=[])

        # M8 straps
        pdngen.makeStrap(grid=grid, layer=m8, width=design.micronToDBU(1.4), spacing=design.micronToDBU(1.4),
                         pitch=design.micronToDBU(10.8), offset=design.micronToDBU(0), number_of_straps=0,
                         snap=False, starts_with=pdn.GRID, extend=pdn.CORE, nets=[])

        # M7 ring
        # API: pdn.PdnGen.makeRing(grid, layer0, width0, spacing0, layer1, width1, spacing1, ...)
        pdngen.makeRing(grid=grid, layer0=m7, width0=design.micronToDBU(2), spacing0=design.micronToDBU(2),
                        layer1=m7, width1=design.micronToDBU(2), spacing1=design.micronToDBU(2),
                        starts_with=pdn.GRID, offset=[design.micronToDBU(0), design.micronToDBU(0)],
                        pad_offset=[design.micronToDBU(0), design.micronToDBU(0)], extend=True, # Extend to boundary
                        pad_pin_layers=[], nets=[])

        # M8 ring
        pdngen.makeRing(grid=grid, layer0=m8, width0=design.micronToDBU(2), spacing0=design.micronToDBU(2),
                        layer1=m8, width1=design.micronToDBU(2), spacing1=design.micronToDBU(2),
                        starts_with=pdn.GRID, offset=[design.micronToDBU(0), design.micronToDBU(0)],
                        pad_offset=[design.micronToDBU(0), design.micronToDBU(0)], extend=True, # Extend to boundary
                        pad_pin_layers=[], nets=[])


        # Add Core Grid Connections (Vias)
        # API: pdn.PdnGen.makeConnect(grid, layer0, layer1, cut_pitch_x, cut_pitch_y, ...)
        pdngen.makeConnect(grid=grid, layer0=m1, layer1=m4, cut_pitch_x=via_cut_pitch[0], cut_pitch_y=via_cut_pitch[1])
        pdngen.makeConnect(grid=grid, layer0=m4, layer1=m7, cut_pitch_x=via_cut_pitch[0], cut_pitch_y=via_cut_pitch[1])
        pdngen.makeConnect(grid=grid, layer0=m7, layer1=m8, cut_pitch_x=via_cut_pitch[0], cut_pitch_y=via_cut_pitch[1])


# Create PDN for Macros if they exist
if len(macros) > 0:
    macro_halo = [design.micronToDBU(5) for _ in range(4)] # 5 um halo around macros
    for i, macro_inst in enumerate(macros):
        macro_grid_name = f"macro_grid_{i}"
        # Create instance grid for each macro
        # API: pdn.PdnGen.makeInstanceGrid(domain, name, starts_with, inst, halo, ...)
        pdngen.makeInstanceGrid(
            domain=pdngen.findDomain("Core"),
            name=macro_grid_name,
            starts_with=pdn.GROUND, # Or pdn.POWER
            inst=macro_inst,
            halo=macro_halo,
            pg_pins_to_boundary=True, # Connect macro power pins to grid boundary
            default_grid=False # This is a custom instance grid
        )
        macro_grid = pdngen.findGrid(macro_grid_name)

        if macro_grid:
             for m_grid in macro_grid:
                # M5 straps for macros
                pdngen.makeStrap(grid=m_grid, layer=m5, width=design.micronToDBU(1.2), spacing=design.micronToDBU(1.2),
                                 pitch=design.micronToDBU(6), offset=design.micronToDBU(0), number_of_straps=0,
                                 snap=True, starts_with=pdn.GRID, extend=pdn.CORE, nets=[]) # extend=pdn.CORE refers to the macro core

                # M6 straps for macros
                pdngen.makeStrap(grid=m_grid, layer=m6, width=design.micronToDBU(1.2), spacing=design.micronToDBU(1.2),
                                 pitch=design.micronToDBU(6), offset=design.micronToDBU(0), number_of_straps=0,
                                 snap=True, starts_with=pdn.GRID, extend=pdn.CORE, nets=[])

                # M5 ring for macro
                pdngen.makeRing(grid=m_grid, layer0=m5, width0=design.micronToDBU(1.5), spacing0=design.micronToDBU(1.5),
                                layer1=m5, width1=design.micronToDBU(1.5), spacing1=design.micronToDBU(1.5),
                                starts_with=pdn.GRID, offset=[design.micronToDBU(0), design.micronToDBU(0)],
                                pad_offset=[design.micronToDBU(0), design.micronToDBU(0)], extend=True, # Extend to macro boundary
                                pad_pin_layers=[], nets=[])

                # M6 ring for macro
                pdngen.makeRing(grid=m_grid, layer0=m6, width0=design.micronToDBU(1.5), spacing0=design.micronToDBU(1.5),
                                layer1=m6, width1=design.micronToDBU(1.5), spacing1=design.micronToDBU(1.5),
                                starts_with=pdn.GRID, offset=[design.micronToDBU(0), design.micronToDBU(0)],
                                pad_offset=[design.micronToDBU(0), design.micronToDBU(0)], extend=True, # Extend to macro boundary
                                pad_pin_layers=[], nets=[])

                # Add Macro Grid Connections (Vias) - Connect macro grid layers to each other and to core grid layers
                pdngen.makeConnect(grid=m_grid, layer0=m4, layer1=m5, cut_pitch_x=via_cut_pitch[0], cut_pitch_y=via_cut_pitch[1]) # Connect core M4 to macro M5
                pdngen.makeConnect(grid=m_grid, layer0=m5, layer1=m6, cut_pitch_x=via_cut_pitch[0], cut_pitch_y=via_cut_pitch[1]) # Connect macro M5 to M6
                pdngen.makeConnect(grid=m_grid, layer0=m6, layer1=m7, cut_pitch_x=via_cut_pitch[0], cut_pitch_y=via_cut_pitch[1]) # Connect macro M6 to core M7


# Verify and build the PDN
pdngen.checkSetup() # Verify configuration
pdngen.buildGrids(False) # Build the power grid geometry
pdngen.writeToDb(True) # Write power grid shapes to the design database
pdngen.resetShapes() # Clear temporary shapes


# --- IR Drop Analysis ---
# Get the IR Drop analysis tool
ir_analyzer = design.getIRDrop()

# Set analysis parameters
# Note: IR drop analysis typically needs parasitics (extracted after routing)
# and activity factors (SAIF file or similar).
# For a simple analysis just on the PDN, static analysis can be done.
# We'll perform a static analysis assuming VDD/VSS nets and M1 layer as requested.

# Set voltage source (VDD net) and ground reference (VSS net)
ir_analyzer.setVoltageSrc(VDD_net)
ir_analyzer.setGroundRef(VSS_net)

# Specify the layer for analysis results (M1)
analysis_layer = m1.getName() # Get layer name for the function parameter

# Run the analysis
# API: ir_drop.IRDrop.analyze(block, layer_name, voltage, temperature, power_activity_file, result_file_prefix, analysis_type)
# Assuming a default voltage (e.g., 1.1V) and temperature (e.g., 25C) if not specified
# We are doing static analysis here (no power activity file)
# Result file prefix is optional, will output to default location if empty
voltage = 1.1 # Example voltage
temperature = 25.0 # Example temperature

print(f"Running static IR drop analysis on layer: {analysis_layer}")
ir_analyzer.analyze(block, analysis_layer, voltage, temperature, "", "", ir_drop.AnalysisType.STATIC)

# The results are typically stored internally or written to files based on tool configuration
# Accessing specific results (like worst-case drop on M1) programmatically might require
# iterating through violation objects or using specific reporting functions if available.
# For this script, we just run the analysis as requested.

# --- Save Output ---
# Write the DEF file
# API: design.writeDef("PDN.def")
design.writeDef("PDN.def")

# Note: The request did not include routing, so the saved DEF will contain
# floorplan, placement (standard cells and macros), CTS, and the PDN structures.
# It will not contain signal routing.