"""
Filename:     plotting.py
Author:       Stephan Rasp, s.rasp@lmu.de

This script contains functions to read pre-processed NetCDF files, do some
final analysis and plot the results.

"""

# Import modules
from helpers import read_netcdf_dataset, get_config, save_fig_and_log
from datetime import datetime, timedelta
import matplotlib.pyplot as plt
import numpy as np


# Define functions
def plot_domain_mean_precipitation_ts(inargs):
    """
    Function to plot time series of domain mean precipitation for each day
    
    Parameters
    ----------
    inargs : argparse object
      Argparse object with all input arguments

    Returns
    -------

    """

    # Read pre-processed data
    rootgroup = read_netcdf_dataset(inargs)
    n_days = rootgroup.dimensions['date'].size
    x = rootgroup.variables['time'][:]

    # Set up figure
    n_cols = 4
    n_rows = int(np.ceil(float(n_days) / n_cols))

    fig, axmat = plt.subplots(n_rows, n_cols, sharex=True, sharey=True,
                              figsize=(10,3*n_rows))   # TODO: figsize
    axflat = np.ravel(axmat)

    # Loop over axes / days
    for iday in range(n_days):
        dateobj = (timedelta(seconds=int(rootgroup.variables['date'][iday])) +
                   datetime(1,1,1))
        datestr = dateobj.strftime(get_config(inargs, 'colors', 'date_fmt'))
        axflat[iday].set_title(datestr)
        if iday % 4 == 0:   # Only left column
            axflat[iday].set_ylabel('Accumulation [mm/h]')
        if iday >= ((n_cols * n_rows) - n_cols):   # Only bottom row
            axflat[iday].set_xlabel('Time [UTC]')

        for group in rootgroup.groups:
            # Get data do be plotted
            # prec: det, obs or ens mean
            # prec_lower/upper: ensemble minimum, maximum
            if group == 'ens':
                prec_array = rootgroup.groups[group].variables['PREC_ACCUM']\
                    [iday, :, :]
                prec = np.mean(prec_array, axis=1)
                prec_lower = np.amin(prec_array, axis=1)
                prec_upper = np.amax(prec_array, axis=1)
            else:
                prec = rootgroup.groups[group].variables['PREC_ACCUM']\
                    [iday, :, 0]

            # Plot data
            axflat[iday].plot(x, prec, label=group,
                              c=get_config(inargs, 'colors', group))
            if group == 'ens':
                axflat[iday].fill_between(x, prec_lower, prec_upper,
                                          where=prec_upper >= prec_lower,
                                          facecolor=get_config(inargs,
                                                               'colors',
                                                               'ens_range'))

    # Finish figure
    axflat[0].legend(loc=0)

    plt.tight_layout()

    # Save figure
    save_fig_and_log(fig, rootgroup, inargs, 'precipitation_ts_individual')


def plot_domain_mean_precipitation_ts_composite(inargs):
    """
    Function to plot time series of domain mean precipitation as a composite over 
    all days

    Parameters
    ----------
    inargs : argparse object
      Argparse object with all input arguments

    Returns
    -------

    """

    # Read pre-processed data
    rootgroup = read_netcdf_dataset(inargs)
    x = rootgroup.variables['time'][:]

    fig, ax = plt.subplots(1, 1, figsize=(3, 3))

    for group in rootgroup.groups:
        prec = rootgroup.groups[group].variables['PREC_ACCUM'][:]
        mean_prec = np.mean(prec, axis=(0,2))
        ax.plot(x, mean_prec, label=group,
                c=get_config(inargs, 'colors', group))

    ax.set_ylabel('Accumulation [mm/h]')
    ax.set_xlabel('Time [UTC]')
    dateobj_start = (timedelta(seconds=int(rootgroup.variables['date'][0])) +
                     datetime(1,1,1))
    datestr_start = dateobj_start.strftime(get_config(inargs, 'colors',
                                                      'date_fmt'))
    dateobj_end = (timedelta(seconds=int(rootgroup.variables['date'][-1])) +
                   datetime(1, 1, 1))
    datestr_end = dateobj_end.strftime(get_config(inargs, 'colors',
                                                  'date_fmt'))
    comp_str = 'Composite ' + datestr_start + ' - ' + datestr_end
    ax.set_title(comp_str)
    ax.legend(loc=0)

    plt.tight_layout()

    # Save figure and log
    save_fig_and_log(fig, rootgroup, inargs, 'precipitation_ts_composite')


def plot_domain_mean_cape_tauc_ts(inargs):
    """
    Function to plot time series of domain mean CAPE abd tau_c for each day

    Parameters
    ----------
    inargs : argparse object
      Argparse object with all input arguments

    Returns
    -------

    """

    # Read pre-processed data
    rootgroup = read_netcdf_dataset(inargs)
    n_days = rootgroup.dimensions['date'].size
    x = rootgroup.variables['time'][:]

    # Set up figure
    n_cols = 4
    n_rows = int(np.ceil(float(n_days) / n_cols))

    fig, axmat = plt.subplots(n_rows, n_cols, sharex=True, sharey=True,
                              figsize=(10,3*n_rows))   # TODO: figsize
    axflat = np.ravel(axmat)

    # Loop over axes / days
    for iday in range(n_days):
        ax1 = axflat[iday]
        ax2 = ax1.twinx()

        dateobj = (timedelta(seconds=int(rootgroup.variables['date'][iday])) +
                   datetime(1,1,1))
        datestr = dateobj.strftime(get_config(inargs, 'colors', 'date_fmt'))
        ax1.set_title(datestr)
        if iday % 4 == 0:   # Only left column
            ax1.set_ylabel('CAPE [J/kg]')
        if iday % 4 == 3:
            ax2.set_ylabel('tau_c [h]')
        if iday >= ((n_cols * n_rows) - n_cols):   # Only bottom row
            ax1.set_xlabel('Time [UTC]')

        for group in ['det', 'ens']:
            for var, ax in zip(['CAPE_ML', 'TAU_C'], [ax1, ax2]):
                # Get data do be plotted
                # prec: det, obs or ens mean
                # prec_lower/upper: ensemble minimum, maximum
                if group == 'ens':
                    array = rootgroup.groups[group].variables[var]\
                        [iday, :, :]
                    mean = np.mean(array, axis=1)
                    lower = np.amin(array, axis=1)
                    upper = np.amax(array, axis=1)
                else:
                    mean = rootgroup.groups[group].variables[var]\
                        [iday, :, 0]

                # Plot data
                ax.plot(x, mean, label=group,
                                  c=get_config(inargs, 'colors', group))
                if group == 'ens':
                    ax.fill_between(x, lower, upper,
                                              where=upper >= lower,
                                              facecolor=get_config(inargs,
                                                                   'colors',
                                                                   'ens_range'))

    # Finish figure
    axflat[0].legend(loc=0)

    plt.tight_layout()

    # Save figure
    save_fig_and_log(fig, rootgroup, inargs, 'cape_tauc_ts_individual')


def plotting(inargs):
    """
    Top-level function called by main.py
    
    Parameters
    ----------
    inargs : argparse object
      Argparse object with all input arguments

    Returns
    -------

    """

    # Call appropriate plotting function
    #plot_domain_mean_precipitation_ts(inargs)
    #plot_domain_mean_precipitation_ts_composite(inargs)

    plot_domain_mean_cape_tauc_ts(inargs)
