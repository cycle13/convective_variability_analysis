"""
Filename:     variability.py
Author:       Stephan Rasp, s.rasp@lmu.de
Description:  Compute variance and mean of coarse grained fields

"""

import argparse
from netCDF4 import Dataset
from datetime import datetime, timedelta
from helpers import pp_exists, get_pp_fn, load_raw_data, make_datelist, \
                    identify_clouds, get_config, create_log_str, \
                    read_netcdf_dataset, save_fig_and_log, get_composite_str, \
                    fit_curve
import matplotlib.pyplot as plt
import numpy as np

################################################################################
# PREPROCESSING FUNCTIONS
################################################################################


def compute_variance(inargs):
    """
    Main analysis routine to coarse grain fields and compute variances.
    
    Parameters
    ----------
    inargs : argparse object
      Argparse object with all input arguments


    """

    # Some preliminaries
    dx = float(get_config(inargs, 'domain', 'dx'))

    # Make the pp NetCDF file
    rootgroup = create_netcdf(inargs)
    rootgroup.variables['cond_m_hist'][:] = 0

    # Load the raw_data
    if inargs.var == 'm':   # Load data for mass flux calculation
        raw_data = load_raw_data(inargs, ['W', 'QC', 'QI', 'QS', 'RHO',
                                          'TTENS_MPHY'], 'ens', lvl=inargs.lvl)
    elif inargs.var == 'prec':   # Load data for precipitation calculation
        raw_data = load_raw_data(inargs, ['PREC_ACCUM'], 'ens')
    else:
        raise Exception('Wrong var! ' + inargs.var)

    # Loop over each time
    for idate, date in enumerate(make_datelist(inargs)):
        print('Computing variance for ' + date)
        for it in range(rootgroup.dimensions['time'].size):
            # Loop over ensemble members
            # Temporarily save the centers of mass and sums
            com_ens_list = []
            sum_ens_list = []
            for ie in range(raw_data.dimensions['ens_no'].size):
                # Identify the clouds
                if inargs.var is 'm':
                    field = raw_data.variables['W'][idate, it, ie]
                    opt_field = (raw_data.variables['QC'][idate, it, ie] +
                                 raw_data.variables['QI'][idate, it, ie] +
                                 raw_data.variables['QS'][idate, it, ie])
                    rho = raw_data.variables['RHO'][idate, it, ie]
                    opt_thresh = 0.

                else:
                    field = raw_data.variables['PREC_ACCUM'][idate, it, ie]
                    opt_field = None
                    rho = None
                    opt_thresh = None

                labels, size_list, sum_list, com_list = \
                    identify_clouds(field, inargs.thresh, opt_field=opt_field,
                                    water=inargs.sep, rho=rho,
                                    dx=dx, neighborhood=inargs.footprint,
                                    return_com=True, opt_thresh=opt_thresh)

                if com_list.shape[0] == 0:   # Accout for empty arrays, Need that?
                    com_list = np.empty((0,2))

                if inargs.var == 'm':
                    sum_list = sum_list * dx * dx   # to convert to mass flux
                com_ens_list.append(com_list)
                sum_ens_list.append(sum_list)

            # Compute the variances and means
            comp_var_mean(inargs, idate, it, rootgroup, com_ens_list,
                          sum_ens_list, raw_data)
    rootgroup.close()


def create_netcdf(inargs):
    """
    
    Parameters
    ----------
    inargs : argparse object
      Argparse object with all input arguments

    Returns
    -------
    rootgroup : NetCDF dataset object

    """

    dimensions = {
        'date':  np.array(make_datelist(inargs, out_format='netcdf')),
        'time': np.arange(inargs.time_start, inargs.time_end + inargs.time_inc,
                          inargs.time_inc),
        'n': np.array([256, 128, 64, 32, 16, 8, 4]),
        'x': np.arange(get_config(inargs, 'domain', 'ana_irange')),
        'y': np.arange(get_config(inargs, 'domain', 'ana_jrange')),
        'cond_bins_mean_m': np.linspace(0, 2e8, 10)[1:],   # TODO: Softcode this stuff
        'cond_bins_m': np.linspace(0, 1e9, 50)[1:],
    }

    variables = {
        'var_m': ['date', 'time', 'n', 'x', 'y'],
        'var_M': ['date', 'time', 'n', 'x', 'y'],
        'var_N': ['date', 'time', 'n', 'x', 'y'],
        'mean_m': ['date', 'time', 'n', 'x', 'y'],
        'mean_M': ['date', 'time', 'n', 'x', 'y'],
        'mean_N': ['date', 'time', 'n', 'x', 'y'],
        'corr_m_N': ['date', 'time', 'n', 'x', 'y'],
        'cond_m_hist': ['n', 'cond_bins_mean_m', 'cond_bins_m'],
    }
    if inargs.var is 'm':
        variables.update({'var_TTENS': ['date', 'time', 'n', 'x', 'y'],
                          'mean_TTENS': ['date', 'time', 'n', 'x', 'y']})

    pp_fn = get_pp_fn(inargs)

    # Create NetCDF file
    rootgroup = Dataset(pp_fn, 'w', format='NETCDF4')
    rootgroup.log = create_log_str(inargs, 'Preprocessing')

    # Create root dimensions and variables
    for dim_name, dim_val in dimensions.items():
        rootgroup.createDimension(dim_name, dim_val.shape[0])
        tmp_var = rootgroup.createVariable(dim_name, 'f8', dim_name)
        tmp_var[:] = dim_val

    # Create variables
    for var_name, var_dims in variables.items():
        tmp_var = rootgroup.createVariable(var_name, 'f8', var_dims)
        # Set all variables to nan by default to save time later
        tmp_var[:] = np.nan
    return rootgroup


def comp_var_mean(inargs, idate, it, rootgroup, com_ens_list, sum_ens_list,
                  raw_data):
    """
    Compute variances and means and save in rootgroup object
    Parameters
    ----------
    inargs : argparse object
      Argparse object with all input arguments
    idate : int
      Date index
    it : int
      Time index
    rootgroup : NetCDF dataset object
      To save data
    com_ens_list : list
      list with centers of mass
    sum_ens_list : list
      list with object sums
    raw_data : NetCDF dataset object
      To load raw data

    """

    # Create temporarty numpy arrays
    arr_shape = rootgroup.variables['var_M'][idate, it, :, :, :].shape
    tmp_var_M = np.zeros(arr_shape) * np.nan
    tmp_var_N = np.zeros(arr_shape) * np.nan
    tmp_var_m = np.zeros(arr_shape) * np.nan
    tmp_mean_M = np.zeros(arr_shape) * np.nan
    tmp_mean_N = np.zeros(arr_shape) * np.nan
    tmp_mean_m = np.zeros(arr_shape) * np.nan
    tmp_corr_m_N = np.zeros(arr_shape) * np.nan

    tmp_cond_hist = np.zeros(rootgroup.variables['cond_m_hist'].shape)

    if inargs.var is 'm':
        # Load raw_data for ttens
        tmp_ttens = raw_data.variables['TTENS_MPHY'][idate, it]
        tmp_var_ttens = np.zeros(arr_shape) * np.nan
        tmp_mean_ttens = np.zeros(arr_shape) * np.nan

    # Loop over different coarsening sizes
    for i_n, n in enumerate(rootgroup.variables['n']):

        # Get size of coarse arrays
        nx = int(np.floor(get_config(inargs, 'domain', 'ana_irange') / n))
        ny = int(np.floor(get_config(inargs, 'domain', 'ana_jrange') / n))

        # Loop over coarse grid boxes
        for ico in range(nx):
            for jco in range(ny):
                # Get limits for each N box
                n = int(n)
                xmin = ico * n
                xmax = (ico + 1) * n
                ymin = jco * n
                ymax = (jco + 1) * n

                # Now loop over the ensemble members and save the relevant lists
                # The terminology follows the mass flux calculations, but
                # this works for prec as well (hopefully)
                ens_m_list = []
                ens_M_list = []
                ens_N_list = []
                ens_m_box_list = []   # This actually saves the mean m for each mem
                if inargs.var is 'm':   # Also compute heating rate sum and var
                    ens_ttens_list = []
                for ie, com_list, sum_list in zip(range(inargs.nens),
                                                  com_ens_list,
                                                  sum_ens_list):

                    # Get the collapsed clouds for each box
                    bool_arr = ((com_list[:, 0] >= xmin) &
                                (com_list[:, 0] < xmax) &
                                (com_list[:, 1] >= ymin) &
                                (com_list[:, 1] < ymax))

                    # This is the array with all clouds for this box and member
                    box_cld_sum = sum_list[bool_arr]

                    # This lists contains all clouds for all members in a box
                    ens_m_list += list(box_cld_sum)

                    # If the array is empty set M to zero
                    if len(box_cld_sum) > 0:
                        ens_M_list.append(np.sum(box_cld_sum))
                        ens_m_box_list.append(np.mean(box_cld_sum))
                    else:
                        ens_M_list.append(0.)
                        ens_m_box_list.append(0.)

                    # This is the number of clouds
                    ens_N_list.append(box_cld_sum.shape[0])

                    if inargs.var is 'm':
                        # This is the MEAN heating rate
                        ens_ttens_list.append(np.mean(tmp_ttens[ie]
                                                      [ico * n:(ico + 1) * n,
                                                       jco * n:(jco + 1) * n]))
                    # End member loop

                # Now convert the list with all clouds for this box
                ens_m_list = np.array(ens_m_list)

                # Calculate statistics and save them in ncdf file
                # Check if x number of members have clouds in them

                if np.sum(np.array(ens_N_list) > 0) >= inargs.minobj:
                    tmp_var_M[i_n, ico, jco] = np.var(ens_M_list, ddof=1)
                    tmp_var_N[i_n, ico, jco] = np.var(ens_N_list, ddof=1)
                    tmp_var_m[i_n, ico, jco] = np.var(ens_m_list, ddof=1)
                    tmp_mean_M[i_n, ico, jco] = np.mean(ens_M_list)
                    tmp_mean_N[i_n, ico, jco] = np.mean(ens_N_list)
                    tmp_mean_m[i_n, ico, jco] = np.mean(ens_m_list)
                    tmp_corr_m_N[i_n, ico, jco] = np.corrcoef(ens_m_box_list,
                                                              ens_N_list)[0, 1]
                    m_bin = np.digitize([np.mean(ens_m_list)],
                                        np.linspace(0, 2e8, 10)[1:-1],
                                        right=True)[0]  #TODO: Softcode!
                    tmp_cond_hist[i_n, m_bin] += np.histogram(ens_m_list, np.linspace(0, 1e9, 50))[0]

                if inargs.var is 'm':
                    tmp_var_ttens[i_n, ico, jco] = np.var(ens_ttens_list, ddof=1)
                    tmp_mean_ttens[i_n, ico, jco] = np.mean(ens_ttens_list)

    # Now write to NetCDF
    rootgroup.variables['var_M'][idate, it] = tmp_var_M
    rootgroup.variables['var_N'][idate, it] = tmp_var_N
    rootgroup.variables['var_m'][idate, it] = tmp_var_m
    rootgroup.variables['mean_M'][idate, it] = tmp_mean_M
    rootgroup.variables['mean_N'][idate, it] = tmp_mean_N
    rootgroup.variables['mean_m'][idate, it] = tmp_mean_m
    rootgroup.variables['corr_m_N'][idate, it] = tmp_corr_m_N

    rootgroup.variables['cond_m_hist'][:] = (rootgroup.variables['cond_m_hist'][:] +
                                             tmp_cond_hist)

    if inargs.var is 'm':
        rootgroup.variables['var_TTENS'][idate, it] = tmp_var_ttens
        rootgroup.variables['mean_TTENS'][idate, it] = tmp_mean_ttens


################################################################################
# PLOTTING FUNCTIONS
################################################################################


def plot_diurnal(inargs):
    """
    Plots the diurnal plots for three different scales.

    Parameters
    ----------
    inargs : argparse object
      Argparse object with all input arguments

    """

    # Load dataset
    rootgroup = read_netcdf_dataset(inargs)
    # The variables have dimensions [date, time, n, x[n], y[n]]

    # Set up figure
    pw = get_config(inargs, 'plotting', 'page_width')
    ratio = 1.

    if inargs.diurnal_individual_days:
        n_days = rootgroup.dimensions['date'].size
        n_cols = 4
        n_rows = int(np.ceil(float(n_days) / n_cols))

        fig, axmat = plt.subplots(n_rows, n_cols, sharex=True, sharey=True,
                                  figsize=(pw, 2.1 * n_rows))
        axflat = np.ravel(axmat)

    else:
        fig, ax = plt.subplots(1, 1, figsize=(pw / 3., pw / 3. * ratio))

    clist = [get_config(inargs, 'colors', 'ens'),
             get_config(inargs, 'colors', 'det'),
             get_config(inargs, 'colors', 'third')]
    labellist = ['Small: ', 'Medium: ', 'Large: ']

    # Do some further calculations to get daily composite
    for i, i_n in enumerate(inargs.diurnal_scale_inds):
        n = rootgroup.variables['n'][i_n]
        nx = int(np.floor(get_config(inargs, 'domain', 'ana_irange') / n))
        ny = int(np.floor(get_config(inargs, 'domain', 'ana_jrange') / n))
        label = labellist[i] + str(int(n * 2.8)) + 'km'

        mean_M = rootgroup.variables['mean_M'][:, :, i_n, :nx, :ny]
        mean_m = rootgroup.variables['mean_m'][:, :, i_n, :nx, :ny]
        mean_N = rootgroup.variables['mean_N'][:, :, i_n, :nx, :ny]
        var_M = rootgroup.variables['var_M'][:, :, i_n, :nx, :ny]
        var_m = rootgroup.variables['var_m'][:, :, i_n, :nx, :ny]
        var_N = rootgroup.variables['var_N'][:, :, i_n, :nx, :ny]
        try:
            corr_m_N = rootgroup.variables['corr_m_N'][:, :, i_n, :nx, :ny]
        except:
            print 'hi'

        # Flatten x and y dimensions
        mean_M = mean_M.reshape(mean_M.shape[0], mean_M.shape[1],
                       mean_M.shape[2] * mean_M.shape[3])
        mean_m = mean_m.reshape(mean_m.shape[0], mean_m.shape[1],
                                mean_m.shape[2] * mean_m.shape[3])
        mean_N = mean_N.reshape(mean_N.shape[0], mean_N.shape[1],
                                mean_N.shape[2] * mean_N.shape[3])
        var_M = var_M.reshape(var_M.shape[0], var_M.shape[1],
                              var_M.shape[2] * var_M.shape[3])
        var_m = var_m.reshape(var_m.shape[0], var_m.shape[1],
                              var_m.shape[2] * var_m.shape[3])
        var_N = var_N.reshape(var_N.shape[0], var_N.shape[1],
                              var_N.shape[2] * var_N.shape[3])
        try:
            corr_m_N = corr_m_N.reshape(corr_m_N.shape[0], corr_m_N.shape[1],
                                        corr_m_N.shape[2] * corr_m_N.shape[3])
        except:
            pass
        # Array now has dimensions [date, time, points]

        if inargs.diurnal_ext_m is not None:
            mean_m = inargs.diurnal_ext_m

        # Computations
        if inargs.plot_type == 'r_v':
            data = var_M / (2. * mean_M * mean_m)
            ylabel = r'$R_V$'
            if inargs.diurnal_ext_m is not None:
                ylabel += r' with fixed $\langle m \rangle$'
        elif inargs.plot_type == 'alpha':
            data = var_N / mean_N
            ylabel = r'$\alpha$'
        elif inargs.plot_type == 'beta':
            data = var_m / (mean_m**2)
            ylabel = r'$\beta$'
        elif inargs.plot_type == 'r_v_alpha':
            data = var_M / ((1 + var_N / mean_N) * mean_M * mean_m)
            ylabel = r'$\alpha$-adjusted $R_V$'
        elif inargs.plot_type == 'r_v_beta':
            data = var_M / ((1 + var_m / (mean_m**2)) * mean_M * mean_m)
            ylabel = r'$\beta$-adjusted $R_V$'
        elif inargs.plot_type == 'r_v_alpha_beta':
            data = var_M / ((var_N / mean_N + var_m / (mean_m**2)) * mean_M *
                            mean_m)
            ylabel = r'$\alpha$ and $\beta$-adjusted $R_V$'
        elif inargs.plot_type == 'corr_m_N':
            data = corr_m_N
            ylabel = r'corr($m$, $N$)'
        elif inargs.plot_type == 'mean_m':
            data = mean_m
            ylabel = r'mean(m)'

        if inargs.diurnal_individual_days:
            for iday, date in enumerate(rootgroup.variables['date']):
                plot_individual_panel(inargs, rootgroup, i, iday, axflat,
                                      n_cols, n_rows, ylabel, data, label,
                                      clist)

        else:
            plot_composite(inargs, rootgroup, i, data, ax, label, clist,
                           ylabel)

    # Finish figure
    if inargs.diurnal_individual_days and inargs.diurnal_legend:
        axflat[0].legend(loc=4, fontsize=8)
        plt.tight_layout()
        plt.subplots_adjust(wspace=0.15, hspace=0.25)
    elif inargs.diurnal_legend:
        ax.legend(loc=2, fontsize=8)



    # Save figure and log
    save_fig_and_log(fig, rootgroup, inargs, inargs.plot_type + '_individual-' +
                     str(inargs.diurnal_individual_days))


def plot_individual_panel(inargs, rootgroup, i, iday, axflat, n_cols, n_rows,
                          ylabel, data, label, clist):
    """
    Plots the individual panels of the diurnal plots for each day.

    Parameters
    ----------
    inargs : argparse object
      Argparse object with all input arguments
    rootgroup : NetCDF dataset object
      Contains the data to be plotted
    i : int
      Scale index
    iday : int
      Day index
    axflat : list
      Flat list containing axes
    n_cols : int
      Number of cols
    n_rows : int
      Number of rows
    ylabel : str
      ylabel
    data : array
      Data to be plotted
    label : str
      Label string
    clist : list
      List with colors
    """
    ax = axflat[iday]
    if i == 0:  # Do once for each axis
        dateobj = (
            timedelta(seconds=int(rootgroup.variables['date'][iday])) +
            datetime(1, 1, 1))
        datestr = dateobj.strftime(
            get_config(inargs, 'plotting', 'date_fmt'))
        # axflat[iday].set_yscale('log')
        # axflat[iday].set_yticks([0.5, 1, 2])
        # axflat[iday].set_yticklabels([0.5, 1, 2])
        # axflat[iday].set_yticks(np.arange(0.1, 3, 0.1), minor='True')
        ax.set_ylim(0.1, 2.5)
        ax.set_xlim(6, 24)
        ax.axhline(y=1, c='gray', zorder=0.1)
        if iday >= ((n_cols * n_rows) - n_cols):  # Only bottom row
            ax.set_xlabel('Time [UTC]')
        if iday % n_cols == 0:  # Only left column
            ax.set_ylabel(ylabel)
        if inargs.diurnal_log:
            ax.set_yscale('log')
            ax.axhline(y=1, c='gray', zorder=0.1)
            ax.set_yticks(np.arange(0.1, 3, 0.1), minor='True')
            ax.set_ylim(inargs.diurnal_ylim[0], inargs.diurnal_ylim[1])
            # Fix from https://github.com/matplotlib/matplotlib/issues/8386/
            from matplotlib.ticker import StrMethodFormatter, NullFormatter
            ax.yaxis.set_major_formatter(StrMethodFormatter('{x:.0f}'))
            ax.yaxis.set_minor_formatter(NullFormatter())
            ax.set_yticks([0.5, 1, 2])
            ax.set_yticklabels([0.5, 1, 2])
            ax.spines['top'].set_visible(False)
            ax.spines['right'].set_visible(False)
            # ax.spines['left'].set_position(('outward', 3))
            ax.spines['bottom'].set_position(('outward', 3))
            ax.text(0.3, 0.9, datestr, fontsize=10,
                    transform=ax.transAxes)
            if iday >= ((n_cols * n_rows) - n_cols):  # Only bottom row
                ax.set_xlabel('Time [UTC]')
                ax.set_xticks([0, 6, 12, 18, 24])

    # Get the data to be plotted
    daily_mean = np.nanmean(data[iday], axis=1)
    per25 = np.nanpercentile(data[iday], 25, axis=1)
    per75 = np.nanpercentile(data[iday], 75, axis=1)

    ax.plot(rootgroup.variables['time'][:], daily_mean,
                      label=label, c=clist[i], zorder=1)
    ax.fill_between(rootgroup.variables['time'][:],
                              per25, per75,
                              where=per25 < per75,
                              linewidth=0, facecolor=clist[i],
                              alpha=0.3, zorder=0.5)


def plot_composite(inargs, rootgroup, i, data, ax, label, clist, ylabel):
    """
    Plots composite panel for diurnal plots.

    Parameters
    ----------
    inargs : argparse object
      Argparse object with all input arguments
    rootgroup : NetCDF dataset object
      Contains the data to be plotted
    i : int
      Scale index
    data : array
      Data to be plotted
    ax : axis object
    label : str
      Label string
    clist : list
      List with colors
    ylabel : str
      ylabel

    """

    # Check how many nans there are in dataset
    num_nan = np.isnan(data).sum()
    num_tot = data.size
    print('Scale index: %i' % (i))
    print('Number of NaNs: %.2e/%.2e' % (num_nan, num_tot))
    print('Percentage of NaNs: %.2f' % (np.float(num_nan) / num_tot * 100.))

    composite_mean = np.nanmean(data, axis=(0,2))
    per25 = np.nanpercentile(data, 25, axis=(0,2))
    per75 = np.nanpercentile(data, 75, axis=(0,2))

    ax.plot(rootgroup.variables['time'][:], composite_mean,
            label=label, c=clist[i], zorder=1,
            linewidth=2)
    ax.fill_between(rootgroup.variables['time'][:],
                              per25, per75,
                              where=per25 < per75,
                              linewidth=0, facecolor=clist[i],
                              alpha=0.3, zorder=0.5)

    if inargs.diurnal_title:
        comp_str = 'Composite ' + get_composite_str(inargs, rootgroup)
        ax.set_title(comp_str)
    if inargs.diurnal_legend:
        ax.legend(loc=2, fontsize=8)
    ax.set_ylabel(ylabel, labelpad=0)
    ax.set_xticks([6, 9, 12, 15, 18, 21, 24])
    ax.set_xticklabels([6, 9, 12, 15, 18, 21, 24])
    ax.set_xlabel('Time [h/UTC]')
    if inargs.diurnal_log:
        ax.set_yscale('log')
        ax.axhline(y=1, c='gray', zorder=0.1)
        ax.set_yticks(np.arange(0.1, 3, 0.1), minor='True')
        ax.set_ylim(inargs.diurnal_ylim[0], inargs.diurnal_ylim[1])
        # Fix from https://github.com/matplotlib/matplotlib/issues/8386/
        from matplotlib.ticker import StrMethodFormatter, NullFormatter
        ax.yaxis.set_major_formatter(StrMethodFormatter('{x:.0f}'))
        ax.yaxis.set_minor_formatter(NullFormatter())
        ax.set_yticks([0.5, 1, 2])
        ax.set_yticklabels([0.5, 1, 2])
    elif inargs.plot_type == 'corr_m_N':
        ax.set_ylim(-1, 1)
        ax.axhline(y=0, c='gray', zorder=0.1)
        ax.yaxis.labelpad = -6
    elif inargs.plot_type == 'mean_m':
        pass
    else:
        ax.set_ylim(0.1, 2.5)
        ax.axhline(y=1, c='gray', zorder=0.1)

    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)
    ax.spines['left'].set_position(('outward', 3))
    ax.spines['bottom'].set_position(('outward', 3))
    ax.set_xlim((6, 24))
    plt.subplots_adjust(left=0.2, right=0.95, bottom=0.2, top=0.95)


def plot_std_vs_mean(inargs):
    """
    Plots standard deviation versus mean plots.

    Parameters
    ----------
    inargs : argparse object
      Argparse object with all input arguments

    """

    dx = float(get_config(inargs, 'domain', 'dx'))
    c_red = get_config(inargs, 'colors', 'third')
    c_blue = get_config(inargs, 'colors', 'ens')
    # Load dataset
    rootgroup = read_netcdf_dataset(inargs)
    # The variables have dimensions [date, time, n, x[n], y[n]]

    # Set up figure
    aspect = 0.8
    pw = get_config(inargs, 'plotting', 'page_width')
    fig, ax = plt.subplots(1, 1, figsize=(pw / 2., pw / 2. * aspect))

    # Data processing
    var = inargs.std_vs_mean_var
    if var not in ['M', 'TTENS']:
        raise Exception('Wrong variable for std_vs_mean.')

    mx_ind = inargs.std_vs_mean_min_scale + 1
    std = np.sqrt(rootgroup.variables['var_' + var][:, :, :mx_ind, :, :])
    mean = rootgroup.variables['mean_' + var][:, :, :mx_ind, :, :]

    # Start with n loop for CC06 fit
    fit_list = []
    for i_n, n in enumerate(rootgroup.variables['n'][:mx_ind]):
        if inargs.std_vs_mean_var == 'TTENS':
            # Multiply with area
            std[:, :, i_n, :, :] *= (n * dx) ** 2
            mean[:, :, i_n, :, :] *= (n * dx) ** 2
        tmp_std = np.ravel(std[:, :, i_n, :, :])
        tmp_mean = np.ravel(mean[:, :, i_n, :, :])
        fit_list.append(fit_curve(tmp_mean, tmp_std))

    # Bin all the data
    std = np.ravel(std)
    mean = np.ravel(mean)

    mask = np.isfinite(mean)

    std = std[mask]
    mean = mean[mask]

    print np.min(mean), np.max(mean)
    # Fit curves for entire dataset
    sqrt_fit = fit_curve(mean, std)
    lin_fit = fit_curve(mean, std, 'linear')
    tmp_x = np.logspace(1, 12, 1000)
    ax.plot(tmp_x, np.sqrt(sqrt_fit * tmp_x), alpha=1, c=c_red,
            linestyle='-', zorder=0.2, label=r'CC06: $y=\sqrt{bx}$')
    ax.plot(tmp_x, lin_fit * tmp_x, alpha=1, color=c_blue,
            linestyle='--', zorder=0.2, label=r'SPPT: $y = bx$')

    nbins = 10
    if inargs.std_vs_mean_var == 'M':
        binedges = np.logspace(6.7, 10, nbins + 1)
    elif inargs.std_vs_mean_var == 'TTENS':
        binedges = np.logspace(1, 8, nbins + 1)
    if inargs.var == 'prec':
        binedges = np.logspace(5, 10, nbins + 1)
    bininds = np.digitize(mean, binedges)
    binmeans = []
    bin5 = []
    bin25 = []
    bin75 = []
    bin95 = []
    binnum = []
    for i in range(1, nbins + 1):
        num = (std[bininds == i]).shape[0]
        if num == 0:
            binmeans.append(np.nan)
            bin25.append(np.nan)
            bin75.append(np.nan)
            bin5.append(np.nan)
            bin95.append(np.nan)
        else:
            binmeans.append(np.average(std[bininds == i]))
            bin25.append(np.percentile(std[bininds == i], 25))
            bin75.append(np.percentile(std[bininds == i], 75))
            bin5.append(np.percentile(std[bininds == i], 5))
            bin95.append(np.percentile(std[bininds == i], 95))
        # I cannot remember what that rescaling of the number was for
        # binnum.append(num / float((std[np.isfinite(std)]).shape[0]) * 50)
        binnum.append(num)
    print binnum
    # xmean = (binedges[:-1] + binedges[1:]) / 2.
    logmean = np.exp((np.log(binedges[:-1]) + np.log(binedges[1:])) / 2.)
    logdiff = np.diff(np.log(binedges))[0]
    logleft = np.exp(np.log(binedges[:-1]) + 0.2 * logdiff)
    logright = np.exp(np.log(binedges[1:]) - 0.2 * logdiff)
    height = np.array(bin75) - np.array(bin25)
    width = logright - logleft

    ax.bar(logleft, height, width, bin25, linewidth=1.3, color='gray',
           edgecolor='gray', align='edge')
    for i, binmean in enumerate(binmeans):
        ax.plot([logleft[i], logright[i]], [binmean, binmean],
                color='black', zorder=2)
        ax.plot([logmean[i], logmean[i]], [bin5[i], bin95[i]],
                color='black', zorder=0.5)

    if inargs.std_vs_mean_var == 'M':
        ax.set_xlim(10**6.7, 1e10)
        ax.set_ylim(0.8e7, 2e9)
        ax.set_xlabel(r'$\langle M \rangle$ [kg s$^{-1}$]')
        ax.set_ylabel(r'$\mathrm{std}(M)$ [kg s$^{-1}$]')
    else:
        ax.set_xlim(1e1, 1e8)
        ax.set_ylim(1e2,7e6)
        ax.set_xlabel(r'$\langle Q \rangle \times A$ [K s$^{-1}$ m$^{2}$]')
        ax.set_ylabel(r'$\mathrm{std}(Q \times A)$ [K s$^{-1}$ m$^{2}$]')

    ax.set_xscale('log')
    ax.set_yscale('log')
    print('Sqrt fit = %.2f' % (sqrt_fit))
    titlestr = 'a) Mass flux' if inargs.std_vs_mean_var == 'M' \
        else 'b) Heating rate'
    ax.set_title(titlestr + ' scaling')

    ax.legend(loc=2, ncol=1, prop={'size': 8})

    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)
    ax.spines['left'].set_position(('outward', 3))
    ax.spines['bottom'].set_position(('outward', 3))

    if inargs.std_vs_mean_plot_inlay:
        if inargs.std_vs_mean_var == 'TTENS':
            raise Exception('Does not work because of line fitting.')
        ax2 = plt.axes([.72, .25, .2, .2], axisbg='lightgray')
        blist = np.array(fit_list) / 1.e8
        x = np.array(rootgroup.variables['n'][:mx_ind]) * dx / 1000.

        ax2.plot(x, blist, c=c_red)
        ax2.scatter(x, blist, c=c_red, s=20)
        ax2.set_title('Slope of CC06 fit', fontsize=7)
        ax2.set_ylabel(r'$b\times 10^8$', fontsize=6, labelpad=0.05)
        ax2.set_xlabel('n [km]', fontsize=6, labelpad=0.07)
        ax2.set_xscale('log')
        ax2.set_xlim(10, 1200)
        from matplotlib.ticker import StrMethodFormatter, NullFormatter
        ax2.xaxis.set_major_formatter(StrMethodFormatter('{x:.0f}'))
        ax2.xaxis.set_minor_formatter(NullFormatter())
        ax2.set_xticks([10, 100, 1000])
        ax2.set_xticklabels([10, 100, 1000], fontsize=6)
        ax2.set_yticks([0.5, 1.5])
        ax2.set_yticklabels([0.5, 1.5], fontsize=6)

    plt.subplots_adjust(left=0.17, right=0.95, bottom=0.17, top = 0.92)

    # Save figure and log
    save_fig_and_log(fig, rootgroup, inargs, 'std_vs_mean_' +
                     inargs.std_vs_mean_var)


def plot_correlation(inargs):
    """
    Plots correlation between N and m in a scatter plot

    Parameters
    ----------
    inargs : argparse object
      Argparse object with all input arguments

    """

    # Read pre-processed data
    rootgroup = read_netcdf_dataset(inargs)

    pw = get_config(inargs, 'plotting', 'page_width')
    fig, axarr = plt.subplots(1, 2, figsize=(pw, pw / 2.5))

    mean_m = rootgroup.variables['mean_m'][:, :, 0, 0, 0]
    mean_N = rootgroup.variables['mean_N'][:, :, 0, 0, 0]


    # axarr[0].plot(rootgroup.variables['time'][:], mean_m, label='non-separated')
    # axarr[1].plot(rootgroup.variables['time'][:], mean_M, label='non-separated')
    axarr[0].scatter(mean_m, mean_N)
    print np.corrcoef(mean_m, mean_N)[0, 1]

    axarr[0].set_xlabel('m')
    axarr[0].set_ylabel('N')
    axarr[0].legend()
    # Save figure and log
    save_fig_and_log(fig, rootgroup, inargs, 'correlation', tight=True)


def plot_CC06b_fig9(inargs):
    """Plots square root of normalized variance against square root of 1/N
    
    Parameters
    ----------
    inargs : argparse object
      Argparse object with all input arguments

    """

    # Read pre-processed data
    rootgroup = read_netcdf_dataset(inargs)

    pw = get_config(inargs, 'plotting', 'page_width')
    fig, ax = plt.subplots(1, 1, figsize=(pw/ 2.5, pw / 2.5))

    # [date, time, n, x, y]
    var_M = rootgroup.variables['var_M'][:, :, :, :, :]
    mean_M = rootgroup.variables['mean_M'][:, :, :, :, :]
    mean_N = rootgroup.variables['mean_N'][:, :, :, :, :]

    y_data = var_M / (mean_M ** 2)
    y_data = np.sqrt(np.nanmean(y_data, axis=(0, 1, 3, 4)))
    x_data = 2. / mean_N
    x_data = np.sqrt(np.nanmean(x_data, axis=(0, 1, 3, 4)))

    # axarr[0].plot(rootgroup.variables['time'][:], mean_m, label='non-separated')
    # axarr[1].plot(rootgroup.variables['time'][:], mean_M, label='non-separated')
    ax.scatter(x_data, y_data)
    ax.plot([0, 2.5], [0, 2.5], c='gray', zorder=0.1)

    ax.set_xlabel('Sqrt(2/N)')
    ax.set_ylabel('Sqrt(Var(M)/M**2)')
    ax.legend()
    # Save figure and log
    save_fig_and_log(fig, rootgroup, inargs, 'CC06b_fig9', tight=True)



################################################################################
# MAIN FUNCTION
################################################################################
def main(inargs):
    """
    Runs the main program

    Parameters
    ----------
    inargs : argparse object
      Argparse object with all input arguments
    """

    # Check if pre-processed file exists
    if (pp_exists(inargs) is False) or (inargs.recompute is True):
        print('Compute preprocessed file: ' + get_pp_fn(inargs))
        # Call preprocessing routine with arguments
        compute_variance(inargs)
    else:
        print('Found pre-processed file: ' + get_pp_fn(inargs))

    # Plotting
    if inargs.plot_type in ['r_v', 'alpha', 'beta', 'r_v_alpha', 'r_v_beta',
                            'r_v_alpha_beta', 'corr_m_N', 'mean_m']:
        plot_diurnal(inargs)
    elif inargs.plot_type == 'std_vs_mean':
        plot_std_vs_mean(inargs)
    elif inargs.plot_type == 'correlation':
        plot_correlation(inargs)
    elif inargs.plot_type == 'CC06b_fig9':
        plot_CC06b_fig9(inargs)
    else:
        print('No or wrong plot_type. Nothing plotted.')


if __name__ == '__main__':

    description = __doc__

    parser = argparse.ArgumentParser(description=description)

    # Analysis arguments
    parser.add_argument('--date_start',
                        type=str,
                        help='Start date of analysis in yyyymmddhh')
    parser.add_argument('--date_end',
                        type=str,
                        help='End date of analysis in yyyymmddhh')
    parser.add_argument('--time_start',
                        type=int,
                        default=1,
                        help='Analysis start time in hrs [including]. \
                              Default = 1')
    parser.add_argument('--time_end',
                        type=int,
                        default=24,
                        help='Analysis end time in hrs [including]. \
                              Default = 24')
    parser.add_argument('--time_inc',
                        type=float,
                        default=1,
                        help='Analysis increment in hrs. Default = 1')
    parser.add_argument('--nens',
                        type=int,
                        default=50,
                        help='Number of ensemble members')
    parser.add_argument('--var',
                        type=str,
                        default='m',
                        help='Type of variable to do calculation for.\
                             Options are [m, prec]')
    parser.add_argument('--lvl',
                        type=int,
                        default=30,
                        help='Vertical level for m analysis.')
    parser.add_argument('--minobj',
                        type=int,
                        default='1',
                        help='Minimum number of clouds in all ensemble members '
                             'for variance calcualtion')
    parser.add_argument('--thresh',
                        type=float,
                        default=1.,
                        help='Threshold for cloud object identification.')
    parser.add_argument('--sep',
                        dest='sep',
                        action='store_true',
                        help='If given, apply cloud separation.')
    parser.set_defaults(sep=False)
    parser.add_argument('--footprint',
                        type=int,
                        default=3,
                        help='Size of search matrix for cloud separation')

    # Plotting arguments
    parser.add_argument('--plot_type',
                        type=str,
                        default='',
                        help='Plot type [std_vs_mean, r_v, alpha, beta, '
                             'r_v_alpha, r_v_beta, r_v_alpha_beta]')
    parser.add_argument('--plot_format',
                        type=str,
                        default='pdf',
                        help='Which format for figure file.')

    # For diurnal
    parser.add_argument('--diurnal_individual_days',
                        dest='diurnal_individual_days',
                        action='store_true',
                        help='If given, plots all days individually for the '
                             'CC06 plots.')
    parser.set_defaults(diurnal_individual_days=False)
    parser.add_argument('--diurnal_title',
                        dest='diurnal_title',
                        action='store_true',
                        help='If given, plot composite title string.')
    parser.set_defaults(diurnal_title=False)
    parser.add_argument('--diurnal_log',
                        dest='diurnal_log',
                        action='store_true',
                        help='If given, plot on log y axis.')
    parser.set_defaults(diurnal_log=False)
    parser.add_argument('--diurnal_legend',
                        dest='diurnal_legend',
                        action='store_true',
                        help='If given, plot legend')
    parser.set_defaults(diurnal_legend=False)
    parser.add_argument('--diurnal_ylim',
                        type=float,
                        nargs='+',
                        default=[0.4, 2.2],
                        help='Ylims for diurnal plots. Default [0.4, 2.2]')
    parser.add_argument('--diurnal_ext_m',
                        type=float,
                        default=None,
                        help='If given, uses constant external m for CC06 '
                             'plots')
    parser.add_argument('--diurnal_scale_inds',
                        type=int,
                        nargs='+',
                        default=[6, 3, 0],
                        help='Scale indices for diurnal plots.')

    # For std_vs_mean
    parser.add_argument('--std_vs_mean_var',
                        type=str,
                        default='M',
                        help='Which variable to use. [M, TTENS]')
    parser.add_argument('--std_vs_mean_xrange',
                        type=float,
                        nargs='+',
                        default=[1e6, 1e10],
                        help='x range for std_vs_mean plots.')
    parser.add_argument('--std_vs_mean_plot_inlay',
                        dest='std_vs_mean_plot_inlay',
                        action='store_true',
                        help='If given, plots fit inlay for std_vs_mean.'
                             'Note: Not working right now!')
    parser.set_defaults(std_vs_mean_plot_inlay=False)
    parser.add_argument('--std_vs_mean_min_scale',
                        type=int,
                        default=6,
                        help='Smallest scale to include in analysis.')

    # General options
    parser.add_argument('--config_file',
                        type=str,
                        default='config.yml',
                        help='Config file in relative directory ../config. \
                              Default = config.yml')
    parser.add_argument('--sub_dir',
                        type=str,
                        default='variability',
                        help='Sub-directory for figures and pp_files')
    parser.add_argument('--plot_name',
                        type=str,
                        default='',
                        help='Custom plot name.')
    parser.add_argument('--pp_name',
                        type=str,
                        default='',
                        help='Custom name for preprocessed file.')
    parser.add_argument('--recompute',
                        dest='recompute',
                        action='store_true',
                        help='If True, recompute pre-processed file.')
    parser.set_defaults(recompute=False)

    args = parser.parse_args()

    main(args)